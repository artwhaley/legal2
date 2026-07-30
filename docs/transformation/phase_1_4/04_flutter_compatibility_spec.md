# Flutter Windows Compatibility Specification

## Purpose

Prove that the eventual Flutter client can operate the EVW data engine in a Windows release build. This is a compatibility harness, not a product prototype.

## Project rules

- Create a Windows-only `flutter_client/` project.
- Pin the exact Flutter/Dart toolchain used by the passing build.
- Use direct Dart SQLite FFI and explicit SQL.
- Do not add an ORM, state-management framework, routing system, design system, or fake screens.
- Keep hand-written Flutter code limited to native SQLite/extension loading, EVW access, and diagnostics.

## Native SQLite

Use the direct `sqlite3` Dart package. Package Windows x64 sqlite-vec 0.1.9 and spellfix native assets. Reuse the existing spellfix source/build path under `third_party/sqlite/spellfix` and `scripts/build_spellfix_windows.ps1` where suitable.

Load extensions using known native entrypoints through Dart FFI. Do not rely on SQL `load_extension`.

Record native binary hashes and build inputs.

## Probe matrix

Run the probe against a copy of the real current v12 EVW and generated fixtures:

- create/open/close;
- schema/version inspection;
- UTF-8, timestamps, nullable values, large IDs, and blobs;
- paged source-thread/message reads;
- FTS5 query and tokenizer behavior;
- spellfix load, rebuild, and query;
- sqlite-vec load, insert, and nearest-neighbor query;
- known 384-dimensional vector rankings;
- category/evidence/artifact/settings CRUD;
- transaction commit and rollback;
- bulk message import and derived-index rebuild;
- backup creation;
- one serialized writer plus scoped readers;
- lock failure visibility;
- clean close and checkpoint;
- forced crash after committed and uncommitted writes;
- recovery and integrity verification.

The release executable must report each check independently. A failure in FTS5, spellfix, sqlite-vec, WAL recovery, backup, or native packaging blocks Phase 2.
