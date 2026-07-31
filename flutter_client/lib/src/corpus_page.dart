import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import 'workspace_controller.dart';

class CorpusPage extends StatelessWidget {
  const CorpusPage({super.key, required this.workspace});

  final WorkspaceController workspace;

  Future<void> _open(BuildContext context) async {
    final file = await openFile(
      acceptedTypeGroups: [
        const XTypeGroup(label: 'EVW', extensions: ['evw']),
      ],
    );
    if (file == null || !context.mounted) return;
    try {
      await workspace.open(file.path);
    } catch (error) {
      // WorkspaceController records open failures; this branch is only for
      // a picker callback failure that occurs before the controller can do so.
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Open failed: $error')));
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: workspace,
    builder: (context, _) {
      final selected = workspace.selectedRevision;
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: workspace.remoteOperationActive
                      ? null
                      : () => _open(context),
                  icon: const Icon(Icons.folder_open),
                  label: const Text('Open EVW'),
                ),
                OutlinedButton.icon(
                  onPressed:
                      !workspace.isOpen || workspace.remoteOperationActive
                      ? null
                      : () => _run(context, workspace.close),
                  icon: const Icon(Icons.close),
                  label: const Text('Close EVW'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (workspace.path != null)
              SelectableText('Open path: ${workspace.path!}'),
            if (workspace.error != null) ...[
              const SizedBox(height: 8),
              _FailureBanner(message: workspace.error!),
            ],
            const SizedBox(height: 16),
            if (!workspace.isOpen)
              const Expanded(
                child: Center(
                  child: Text('Open a v15 .evw file to inspect it.'),
                ),
              )
            else
              Expanded(
                child: ListView(
                  children: [
                    Text(
                      'Working corpora',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 8),
                    if (workspace.corpora.isEmpty)
                      const Text('This EVW contains no working corpora.')
                    else
                      ...workspace.corpora.map(
                        (corpus) => _CorpusTile(
                          corpus: corpus,
                          selected: workspace.selectedCorpus?.id == corpus.id,
                          enabled: !workspace.remoteOperationActive,
                          onTap: () => _run(
                            context,
                            () => workspace.selectCorpus(corpus.id),
                          ),
                        ),
                      ),
                    if (selected != null) ...[
                      const SizedBox(height: 16),
                      _RevisionCard(workspace: workspace),
                    ],
                  ],
                ),
              ),
          ],
        ),
      );
    },
  );

  void _run(BuildContext context, VoidCallback operation) {
    try {
      operation();
    } catch (error) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

class _CorpusTile extends StatelessWidget {
  const _CorpusTile({
    required this.corpus,
    required this.selected,
    required this.enabled,
    required this.onTap,
  });

  final dynamic corpus;
  final bool selected;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final unavailable = corpus.currentRevisionId == null;
    return Card(
      color: selected ? Theme.of(context).colorScheme.secondaryContainer : null,
      child: ListTile(
        enabled: enabled,
        title: Text(corpus.name as String),
        subtitle: Text(
          unavailable
              ? 'Unavailable: no current revision'
              : 'Current revision ${corpus.currentRevisionId}',
        ),
        trailing: unavailable
            ? const Icon(Icons.block)
            : const Icon(Icons.chevron_right),
        onTap: unavailable ? null : onTap,
      ),
    );
  }
}

class _RevisionCard extends StatelessWidget {
  const _RevisionCard({required this.workspace});

  final WorkspaceController workspace;

  @override
  Widget build(BuildContext context) {
    final revision = workspace.selectedRevision!;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Wrap(
          spacing: 24,
          runSpacing: 8,
          children: [
            Text(
              'Ready revision ${revision.number}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            Text('Messages: ${revision.messages}'),
            Text('Estimated tokens: ${revision.tokens}'),
            Text('Scope: ${revision.scopeHash.substring(0, 12)}'),
            Text('Index generation: ${revision.generation ?? '-'}'),
            Text('FTS: ${revision.ftsStatus ?? '-'}'),
            Text(
              'Message embeddings: ${revision.messageEmbeddingStatus ?? '-'}',
            ),
          ],
        ),
      ),
    );
  }
}

class _FailureBanner extends StatelessWidget {
  const _FailureBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) => MaterialBanner(
    content: SelectableText('FAILED\n$message'),
    actions: const [SizedBox.shrink()],
  );
}
