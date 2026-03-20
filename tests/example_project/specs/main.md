---
title: Example Project
type: project
status: active
owners:
  - example-team
last_updated: 2026-03-20
---

# Project Spec

## Purpose

A simplified example project demonstrating task management with boards and cards, user authentication, and a data layer.

## How to Use This Directory

Each subdirectory contains spec files for a specific area of the project. Start with `domains/` for high-level domain specs, then explore `features/` for specific feature specs.

## Global Constraints

- All features must be covered by tests.
- Database operations must go through the data layer.
- Authentication is required for all task management operations.

## Domains

- [Task Management](domains/task-management.md)
- [Authentication](domains/authentication.md)
- [Data Layer](domains/data-layer.md)

## Core Architecture

See [architecture.md](architecture.md) for an overview of system components and data flow.

## Active Features

- [Create Task](features/create-task.md)
- [Edit Task](features/edit-task.md)
- [Delete Task](features/delete-task.md)
- [Login](features/login.md)
- [Logout](features/logout.md)

## Key Decisions

No decisions recorded yet.

## Agent Working Rules

- Always update `last_updated` in frontmatter when modifying a spec file.
- New features must link back to their parent domain.
- Decisions must be recorded in `decisions/` before implementation begins.
