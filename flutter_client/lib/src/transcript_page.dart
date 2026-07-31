import 'package:flutter/material.dart';

import 'transcript_editor.dart';
import 'workstation_widgets.dart';
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
        return const WorkstationPage(
          title: 'Transcript review',
          description:
              'Read the selected revision, create evidence blocks, and adjust exact context and relevance boundaries.',
          child: EmptyWorkspaceState(
            icon: Icons.subject_outlined,
            title: 'Transcript review requires a working corpus',
            message:
                'Select a ready working corpus on Corpus to use Transcript.',
          ),
        );
      }
      return WorkstationPage(
        title: 'Transcript review',
        description:
            'Read the selected revision, create evidence blocks, and adjust exact context and relevance boundaries.',
        child: TranscriptEvidenceEditor(
          database: database,
          revision: revision,
          controller: workspace.transcriptController,
          isPageActive: isPageActive,
        ),
      );
    },
  );
}
