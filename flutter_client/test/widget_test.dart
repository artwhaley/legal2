import 'dart:io';

import 'package:evw_client/main.dart';
import 'package:evw_client/src/evw_database.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqlite3/sqlite3.dart';

void main() {
  testWidgets('v15 viewer starts without silently selecting a revision', (
    tester,
  ) async {
    await tester.pumpWidget(const EvwViewerApp());
    expect(find.text('Open a v15 .evw file to inspect it.'), findsOneWidget);
    expect(find.text('EVW v15 viewer'), findsOneWidget);
  });

  test('runtime rejects a v14 file', () {
    final directory = Directory.systemTemp.createTempSync('evw_v15_test_');
    final path = '${directory.path}${Platform.pathSeparator}old.evw';
    final db = sqlite3.open(path);
    db.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)');
    db.execute('INSERT INTO schema_version VALUES (14)');
    db.dispose();
    try {
      expect(() => EvwDatabase.open(path), throwsA(isA<StateError>()));
    } finally {
      File(path).deleteSync();
      directory.deleteSync();
    }
  });
}
