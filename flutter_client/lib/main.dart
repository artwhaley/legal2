import 'dart:ffi';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:sqlite3/open.dart' as sqopen;
import 'src/compatibility_probe.dart';
import 'src/app_theme.dart';
import 'src/native_extensions.dart';
import 'src/server_gateway.dart';
import 'src/workspace_view.dart';

void main(List<String> args) {
  sqopen.open.overrideFor(sqopen.OperatingSystem.windows, _openSqlite3);
  final path = _argumentValue(args, '--evw');
  final serverUrl = serverUrlFromArgs(args);
  if (args.contains('--probe')) {
    if (path == null) throw ArgumentError('--probe requires --evw PATH');
    try {
      runCompatibilityProbe(path);
      exit(0);
    } catch (error, stackTrace) {
      stderr.writeln('EVW probe: FAILED');
      stderr.writeln(error);
      stderr.writeln(stackTrace);
      exit(1);
    }
  }
  loadSqliteVec();
  runApp(
    EvwViewerApp(
      initialPath: path,
      serverUrl: serverUrl,
      gateway: HttpServerGateway(serverUrl),
    ),
  );
}

DynamicLibrary _openSqlite3() {
  for (final name in ['sqlite3.dll', 'winsqlite3.dll']) {
    try {
      return DynamicLibrary.open(name);
    } catch (_) {}
  }
  throw StateError('Cannot load sqlite3.dll');
}

String? _argumentValue(List<String> args, String name) {
  final index = args.indexOf(name);
  if (index < 0) return null;
  if (index + 1 >= args.length || args[index + 1].startsWith('--'))
    throw ArgumentError('$name requires a path');
  return args[index + 1];
}

String serverUrlFromArgs(List<String> args) {
  final value = _argumentValue(args, '--server-url') ?? 'http://127.0.0.1:8710';
  final uri = Uri.tryParse(value);
  if (uri == null ||
      !{'http', 'https'}.contains(uri.scheme) ||
      uri.host.isEmpty) {
    throw ArgumentError(
      '--server-url must be an absolute http:// or https:// URL',
    );
  }
  return value.replaceFirst(RegExp(r'/+$'), '');
}

class EvwViewerApp extends StatelessWidget {
  const EvwViewerApp({
    super.key,
    this.initialPath,
    this.serverUrl = 'http://127.0.0.1:8710',
    this.gateway,
  });
  final String? initialPath;
  final String serverUrl;
  final ServerGateway? gateway;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'EVW v15 viewer',
    debugShowCheckedModeBanner: false,
    theme: AppTheme.light,
    home: WorkspaceView(
      initialPath: initialPath,
      gateway: gateway ?? UnconfiguredServerGateway(baseUrl: serverUrl),
    ),
  );
}
