import 'package:flutter/material.dart';

import 'transcript_editor.dart';
import 'workspace_controller.dart';

class TranscriptPage extends StatelessWidget {
  const TranscriptPage({
    super.key,
    required this.workspace,
    required this.isPageActive,
  });

  final WorkspaceController workspace;
  final bool isPageActive;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: workspace,
    builder: (context, _) {
      final database = workspace.database;
      final revision = workspace.selectedRevision;
      if (database == null || revision == null) {
        return const Center(
          child: Text(
            'Select a ready working corpus on Corpus to use Transcript.',
          ),
        );
      }
      return TranscriptEvidenceEditor(
        database: database,
        revision: revision,
        controller: workspace.transcriptController,
        isPageActive: isPageActive,
      );
    },
  );
}
