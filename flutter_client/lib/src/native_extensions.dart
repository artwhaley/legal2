import 'dart:ffi';

import 'package:flutter/foundation.dart';
import 'package:sqlite3/sqlite3.dart';

/// Loads the sqlite-vec native extension through Dart FFI.
///
/// Uses [SqliteExtension.inLibrary] to load entrypoints from bundled DLLs.
/// Does not rely on SQL `load_extension`.

DynamicLibrary _loadNativeLib(String name) {
  // In release builds, the DLLs are bundled in the executable directory
  // by Windows runner's CMakeLists.txt
  final candidates = [
    // Development: relative to project root
    'windows/native/$name',
    // Release build: alongside the executable
    '$name',
  ];
  for (final path in candidates) {
    try {
      return DynamicLibrary.open(path);
    } catch (_) {
      continue;
    }
  }
  throw Exception(
    'Cannot load native library: $name. Tried: ${candidates.join(", ")}',
  );
}

/// Load sqlite-vec extension via auto-extension mechanism.
void loadSqliteVec() {
  final lib = _loadNativeLib('vec0.dll');
  sqlite3.ensureExtensionLoaded(
    SqliteExtension.inLibrary(lib, 'sqlite3_vec_init'),
  );
  debugPrint('[native] sqlite-vec loaded from vec0.dll');
}
