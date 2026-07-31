import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import 'workstation_widgets.dart';
import 'workspace_controller.dart';
import 'splitter.dart';

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
      return WorkstationPage(
        title: 'Working corpus',
        description:
            'Open an EVW and select the ready revision that scopes search, conversation, transcript, and print work.',
        actions: [
          FilledButton.icon(
            onPressed: workspace.remoteOperationActive
                ? null
                : () => _open(context),
            icon: const Icon(Icons.folder_open_outlined),
            label: const Text('Open EVW'),
          ),
          OutlinedButton.icon(
            onPressed: !workspace.isOpen || workspace.remoteOperationActive
                ? null
                : () => _run(context, workspace.close),
            icon: const Icon(Icons.close),
            label: const Text('Close EVW'),
          ),
        ],
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (workspace.path != null)
              SectionSurface(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 9,
                ),
                backgroundColor: Theme.of(
                  context,
                ).colorScheme.surfaceContainerLow,
                child: Row(
                  children: [
                    Icon(
                      Icons.folder_open_outlined,
                      size: 17,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'OPEN WORKSPACE',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: SelectableText(workspace.path!)),
                  ],
                ),
              ),
            if (workspace.error != null) ...[
              if (workspace.path != null) const SizedBox(height: 10),
              OperationalMessage(
                message: workspace.error!,
                label: 'FAILED',
                tone: OperationalTone.failure,
              ),
            ],
            if (workspace.path != null || workspace.error != null)
              const SizedBox(height: 14),
            Expanded(
              child: !workspace.isOpen
                  ? const EmptyWorkspaceState(
                      icon: Icons.inventory_2_outlined,
                      title: 'No evidence workspace is open',
                      message: 'Open a v15 .evw file to inspect it.',
                    )
                  : LayoutBuilder(
                      builder: (context, constraints) {
                        final corpora = _CorpusList(
                          workspace: workspace,
                          onSelect: (corpusId) => _run(
                            context,
                            () => workspace.selectCorpus(corpusId),
                          ),
                        );
                        final revision = selected == null
                            ? const EmptyWorkspaceState(
                                icon: Icons.rule_folder_outlined,
                                title: 'No ready corpus selected',
                                message:
                                    'Choose an available working corpus to inspect its current revision.',
                              )
                            : _RevisionCard(workspace: workspace);
                        if (constraints.maxWidth >= 1040) {
                          return ResizableSplitter(
                            primary: corpora,
                            secondary: revision,
                            initialPrimarySize:
                                workspace.splitSize(
                                  WorkspaceController.corpusListSplit,
                                ) ??
                                360,
                            primaryMin: 280,
                            secondaryMin: 360,
                            onDragEnd: (value) => workspace.persistSplitSize(
                              WorkspaceController.corpusListSplit,
                              value,
                            ),
                          );
                        }
                        return ListView(
                          children: [
                            SizedBox(height: 260, child: corpora),
                            const SizedBox(height: 14),
                            revision,
                          ],
                        );
                      },
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

class _CorpusList extends StatelessWidget {
  const _CorpusList({required this.workspace, required this.onSelect});

  final WorkspaceController workspace;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) => SectionSurface(
    padding: EdgeInsets.zero,
    clipBehavior: Clip.antiAlias,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(14, 13, 14, 11),
          child: SectionHeader(
            title: 'Working corpora',
            description: 'Available named scopes in this EVW.',
            leading: Icon(Icons.storage_outlined, size: 19),
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: workspace.corpora.isEmpty
              ? const Center(
                  child: Text('This EVW contains no working corpora.'),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(8),
                  itemCount: workspace.corpora.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 6),
                  itemBuilder: (context, index) {
                    final corpus = workspace.corpora[index];
                    return _CorpusTile(
                      corpus: corpus,
                      selected: workspace.selectedCorpus?.id == corpus.id,
                      enabled: !workspace.remoteOperationActive,
                      onTap: () => onSelect(corpus.id),
                    );
                  },
                ),
        ),
      ],
    ),
  );
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
      color: selected
          ? Theme.of(
              context,
            ).colorScheme.primaryContainer.withValues(alpha: 0.7)
          : Theme.of(context).colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: BorderSide(
          color: selected
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.outlineVariant,
          width: selected ? 1.5 : 1,
        ),
      ),
      child: ListTile(
        enabled: enabled,
        leading: Icon(
          unavailable ? Icons.block_outlined : Icons.rule_folder_outlined,
        ),
        title: Text(
          corpus.name as String,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          unavailable
              ? 'Unavailable: no current revision'
              : 'Current revision ${corpus.currentRevisionId}',
        ),
        trailing: selected
            ? const Icon(Icons.check_circle, size: 20)
            : unavailable
            ? null
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
    return SectionSurface(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SectionHeader(
            title: 'Ready revision ${revision.number}',
            description: 'Current persisted index and scope metadata.',
            leading: Icon(
              Icons.verified_outlined,
              size: 19,
              color: Theme.of(context).colorScheme.primary,
            ),
            trailing: const StatusPill(
              label: 'READY',
              icon: Icons.check,
              color: Color(0xff2c6a4b),
            ),
          ),
          const Divider(height: 28),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _RevisionMetric(
                label: 'Messages',
                value: '${revision.messages}',
                icon: Icons.forum_outlined,
              ),
              _RevisionMetric(
                label: 'Estimated tokens',
                value: '${revision.tokens}',
                icon: Icons.data_object,
              ),
              _RevisionMetric(
                label: 'Scope',
                value: revision.scopeHash.substring(0, 12),
                icon: Icons.fingerprint,
              ),
              _RevisionMetric(
                label: 'Index generation',
                value: '${revision.generation ?? '-'}',
                icon: Icons.layers_outlined,
              ),
              _RevisionMetric(
                label: 'FTS',
                value: revision.ftsStatus ?? '-',
                icon: Icons.manage_search,
              ),
              _RevisionMetric(
                label: 'Message embeddings',
                value: revision.messageEmbeddingStatus ?? '-',
                icon: Icons.hub_outlined,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RevisionMetric extends StatelessWidget {
  const _RevisionMetric({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Container(
    width: 210,
    padding: const EdgeInsets.all(11),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      borderRadius: BorderRadius.circular(4),
    ),
    child: Row(
      children: [
        Icon(icon, size: 18, color: Theme.of(context).colorScheme.primary),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 2),
              Text(
                value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ],
          ),
        ),
      ],
    ),
  );
}
