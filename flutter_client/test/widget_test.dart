import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:evw_client/main.dart';
import 'package:evw_client/src/conversation_page.dart';
import 'package:evw_client/src/evw_database.dart';
import 'package:evw_client/src/search_page.dart';
import 'package:evw_client/src/server_gateway.dart';
import 'package:evw_client/src/workspace_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqlite3/sqlite3.dart';

void main() {
  testWidgets('v15 viewer starts without silently selecting a revision', (
    tester,
  ) async {
    await tester.pumpWidget(const EvwViewerApp());
    expect(find.text('Open a v15 .evw file to inspect it.'), findsOneWidget);
    expect(find.text('EVW v15 viewer'), findsOneWidget);
    expect(find.text('Corpus'), findsOneWidget);
    expect(find.text('Search'), findsOneWidget);
    expect(find.text('Conversation'), findsOneWidget);
    expect(find.text('Transcript'), findsOneWidget);
    expect(find.text('Print output'), findsOneWidget);
  });

  test('startup server URL parsing is strict and deterministic', () {
    expect(serverUrlFromArgs(const []), 'http://127.0.0.1:8710');
    expect(
      serverUrlFromArgs(const ['--server-url', 'https://example.test/']),
      'https://example.test',
    );
    expect(
      () => serverUrlFromArgs(const ['--server-url', 'ftp://example.test']),
      throwsArgumentError,
    );
    expect(
      () => serverUrlFromArgs(const ['--server-url', 'not a URL']),
      throwsArgumentError,
    );
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
      directory.deleteSync(recursive: true);
    }
  });

  test('conversation probability groups use the exact server enum', () {
    final result = {
      'results': [
        {
          'classification_status': 'model_classified',
          'probability': 'high_probability',
          'statement': 'High',
        },
        {
          'classification_status': 'model_classified',
          'probability': 'lower_probability',
          'statement': 'Lower',
        },
        {
          'classification_status': 'unclassified',
          'probability': null,
          'statement': 'Unclassified',
        },
      ],
    };
    expect(
      classifiedConversationResults(
        result,
        probability: 'high_probability',
      ).single['statement'],
      'High',
    );
    expect(
      classifiedConversationResults(
        result,
        probability: 'lower_probability',
      ).single['statement'],
      'Lower',
    );
  });

  test('search evidence provenance follows the selected search mode', () {
    expect(evidenceCreatorForSearchMode('fts'), 'fts_search');
    expect(evidenceCreatorForSearchMode('embedding'), 'embedding_search');
    expect(() => evidenceCreatorForSearchMode('unknown'), throwsArgumentError);
  });

  testWidgets('only the selected tab marks its transcript active', (
    tester,
  ) async {
    await tester.pumpWidget(const EvwViewerApp());
    final conversationFinder = find.byType(
      ConversationPage,
      skipOffstage: false,
    );
    expect(
      tester.widget<ConversationPage>(conversationFinder).isPageActive,
      isFalse,
    );
    await tester.tap(find.text('Conversation'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<ConversationPage>(conversationFinder).isPageActive,
      isTrue,
    );
  });

  testWidgets('application exit is refused during a remote operation', (
    tester,
  ) async {
    await tester.pumpWidget(
      const EvwViewerApp(gateway: UnconfiguredServerGateway()),
    );
    final dynamic state = tester.state(find.byType(WorkspaceView));
    final lease = state.workspace.beginRemoteOperation('test request');
    await tester.pump();

    expect(await tester.binding.handleRequestAppExit(), AppExitResponse.cancel);
    await tester.pump();
    expect(find.textContaining('Cannot close the application'), findsOneWidget);

    lease.release();
    await tester.pump();
    expect(await tester.binding.handleRequestAppExit(), AppExitResponse.exit);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
