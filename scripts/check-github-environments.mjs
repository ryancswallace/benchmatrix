#!/usr/bin/env node
import {execFileSync} from "node:child_process";
import {readdir, readFile} from "node:fs/promises";
import path from "node:path";
import yaml from "js-yaml";

const WORKFLOW_DIR = ".github/workflows";
const API_VERSION = "2022-11-28";
const LITERAL_EXPRESSION = /^\s*\$\{\{\s*(["'])(.*)\1\s*\}\}\s*$/;

function parseRepositoryFromRemote(remoteUrl) {
    const httpsMatch = remoteUrl.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?$/);
    if (httpsMatch) {
        return `${httpsMatch[1]}/${httpsMatch[2]}`;
    }

    const sshMatch = remoteUrl.match(/^git@github\.com:([^/]+)\/([^/]+?)(?:\.git)?$/);
    if (sshMatch) {
        return `${sshMatch[1]}/${sshMatch[2]}`;
    }

    throw new Error(`Cannot infer GitHub repository from origin URL: ${remoteUrl}`);
}

function repositoryFullName() {
    if (process.env.GITHUB_REPOSITORY) {
        return process.env.GITHUB_REPOSITORY;
    }

    const remoteUrl = execFileSync("git", ["remote", "get-url", "origin"], {encoding: "utf8"}).trim();
    return parseRepositoryFromRemote(remoteUrl);
}

function literalEnvironmentName(value) {
    if (typeof value !== "string") {
        return undefined;
    }

    const expressionMatch = value.match(LITERAL_EXPRESSION);
    if (expressionMatch) {
        return expressionMatch[2];
    }

    if (value.includes("${{")) {
        return undefined;
    }

    return value;
}

function environmentName(environment) {
    if (typeof environment === "string") {
        return literalEnvironmentName(environment);
    }

    if (environment && typeof environment === "object" && "name" in environment) {
        return literalEnvironmentName(environment.name);
    }

    return undefined;
}

async function workflowFiles() {
    let entries;
    try {
        entries = await readdir(WORKFLOW_DIR, {withFileTypes: true});
    } catch (error) {
        if (error?.code === "ENOENT") {
            return [];
        }
        throw error;
    }

    return entries
        .filter(entry => entry.isFile() && /\.ya?ml$/.test(entry.name))
        .map(entry => path.join(WORKFLOW_DIR, entry.name))
        .sort();
}

async function referencedEnvironments() {
    const environments = new Map();

    for (const filePath of await workflowFiles()) {
        const content = await readFile(filePath, "utf8");
        const workflow = yaml.load(content);
        const jobs = workflow?.jobs;
        if (!jobs || typeof jobs !== "object") {
            continue;
        }

        for (const [jobId, job] of Object.entries(jobs)) {
            const name = environmentName(job?.environment);
            if (!name) {
                continue;
            }

            const locations = environments.get(name) ?? [];
            locations.push(`${filePath} (${jobId})`);
            environments.set(name, locations);
        }
    }

    return environments;
}

async function declaredSettingsEnvironments() {
    let content;
    try {
        content = await readFile(".github/settings.yml", "utf8");
    } catch (error) {
        if (error?.code === "ENOENT") {
            return new Set();
        }
        throw error;
    }

    const settings = yaml.load(content);
    return new Set((settings?.environments ?? [])
        .map(environment => environment?.name)
        .filter(name => typeof name === "string")
        .map(name => name.toLowerCase()));
}

async function fetchGitHubEnvironments(repository) {
    const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
    const headers = {
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "benchmatrix-workflow-env-lint",
    };
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }

    const names = new Set();
    for (let page = 1; ; page += 1) {
        const url = `https://api.github.com/repos/${repository}/environments?per_page=100&page=${page}`;
        const response = await fetch(url, {headers});
        if (!response.ok) {
            const detail = await response.text();
            throw new Error(`GitHub environments request failed with HTTP ${response.status}: ${detail}`);
        }

        const payload = await response.json();
        for (const environment of payload.environments ?? []) {
            names.add(environment.name.toLowerCase());
        }

        if ((payload.environments ?? []).length < 100) {
            break;
        }
    }

    return names;
}

function printMissing(repository, missing, declared) {
    console.error(`Missing live GitHub environments for ${repository}:`);
    for (const [name, locations] of missing) {
        const status = declared.has(name.toLowerCase())
            ? "declared in .github/settings.yml, but not synced to GitHub"
            : "not declared in .github/settings.yml";
        console.error(`  - ${name}: ${locations.join(", ")} (${status})`);
    }

    const undeclared = missing.filter(([name]) => !declared.has(name.toLowerCase()));
    if (undeclared.length > 0) {
        console.error("");
        console.error("Add undeclared environments to .github/settings.yml or create them with:");
        for (const [name] of undeclared) {
            console.error(`  gh api --method PUT repos/${repository}/environments/${encodeURIComponent(name)}`);
        }
        return;
    }

    console.error("");
    console.error("These environments are declared in .github/settings.yml. Merge to the default branch and let the GitHub Settings app sync them, or check the app installation/logs if they should already exist.");
}

const repository = repositoryFullName();
const referenced = await referencedEnvironments();
if (referenced.size === 0) {
    console.log("No literal GitHub Actions environments are referenced by workflows.");
    process.exit(0);
}

const declared = await declaredSettingsEnvironments();
const existing = await fetchGitHubEnvironments(repository);
const missing = [...referenced].filter(([name]) => !existing.has(name.toLowerCase()));
if (missing.length > 0) {
    printMissing(repository, missing, declared);
    process.exit(1);
}

console.log(`All ${referenced.size} referenced GitHub Actions environment(s) exist for ${repository}.`);
