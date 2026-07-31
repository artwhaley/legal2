import 'package:flutter/material.dart';

import 'evw_models.dart';
import 'workstation_widgets.dart';
import 'workspace_controller.dart';

class PrintOutputPage extends StatefulWidget {
  const PrintOutputPage({super.key, required this.workspace});

  final WorkspaceController workspace;

  @override
  State<PrintOutputPage> createState() => _PrintOutputPageState();
}

class _PrintOutputPageState extends State<PrintOutputPage> {
  final TextEditingController _title = TextEditingController();
  final TextEditingController _exhibit = TextEditingController();
  final TextEditingController _caseNumber = TextEditingController();
  List<PrintableArtifactGroupSummary> _groups = const [];
  List<PrintableArtifactSummary> _artifacts = const [];
  PrintableArtifactDocument? _document;
  int? _groupId;
  int? _artifactId;
  int? _evidenceBlockId;
  int? _loadedRevisionId;
  int? _loadedEvidenceVersion;
  String? _error;

  WorkspaceController get workspace => widget.workspace;

  @override
  void initState() {
    super.initState();
    workspace.addListener(_onWorkspaceChanged);
    _reload();
  }

  @override
  void dispose() {
    workspace.removeListener(_onWorkspaceChanged);
    _title.dispose();
    _exhibit.dispose();
    _caseNumber.dispose();
    super.dispose();
  }

  void _onWorkspaceChanged() {
    final revisionId = workspace.selectedRevision?.id;
    if (revisionId != _loadedRevisionId ||
        workspace.evidenceDataVersion != _loadedEvidenceVersion) {
      _reload();
    } else if (mounted) {
      setState(() {});
    }
  }

  void _reload() {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      _groups = const [];
      _artifacts = const [];
      _document = null;
      _groupId = null;
      _artifactId = null;
      _evidenceBlockId = null;
      _loadedRevisionId = null;
      _loadedEvidenceVersion = null;
      if (mounted) setState(() {});
      return;
    }
    try {
      _loadedRevisionId = revision.id;
      _loadedEvidenceVersion = workspace.evidenceDataVersion;
      _groups = database.printableArtifactGroups(revision.datasetId);
      if (_groupId == null || !_groups.any((group) => group.id == _groupId)) {
        _groupId = _groups.isEmpty ? null : _groups.first.id;
      }
      _artifacts = _groupId == null
          ? const []
          : database.printableArtifacts(_groupId!);
      if (_artifactId == null ||
          !_artifacts.any((item) => item.id == _artifactId)) {
        _artifactId = _artifacts.isEmpty ? null : _artifacts.first.id;
      }
      _document = _artifactId == null
          ? null
          : database.printableArtifactDocument(
              revisionId: revision.id,
              artifactId: _artifactId!,
            );
      final artifact = _document?.artifact;
      if (artifact != null) {
        _setText(_title, artifact.title);
        _setText(_exhibit, artifact.exhibitNumber);
        _setText(_caseNumber, artifact.caseNumber);
      }
      _error = null;
    } catch (error) {
      _error = '$error';
    }
    if (mounted) setState(() {});
  }

  void _setText(TextEditingController controller, String value) {
    if (controller.text == value) return;
    controller.value = controller.value.copyWith(
      text: value,
      selection: TextSelection.collapsed(offset: value.length),
      composing: TextRange.empty,
    );
  }

  void _selectGroup(int? groupId) {
    if (groupId == null) return;
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) return;
    try {
      _groupId = groupId;
      _artifacts = database.printableArtifacts(groupId);
      _artifactId = _artifacts.isEmpty ? null : _artifacts.first.id;
      _document = _artifactId == null
          ? null
          : database.printableArtifactDocument(
              revisionId: revision.id,
              artifactId: _artifactId!,
            );
      _syncMetadata();
      setState(() => _error = null);
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _selectArtifact(int artifactId) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) return;
    try {
      _artifactId = artifactId;
      _document = database.printableArtifactDocument(
        revisionId: revision.id,
        artifactId: artifactId,
      );
      _syncMetadata();
      setState(() => _error = null);
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _syncMetadata() {
    final artifact = _document?.artifact;
    if (artifact == null) return;
    _setText(_title, artifact.title);
    _setText(_exhibit, artifact.exhibitNumber);
    _setText(_caseNumber, artifact.caseNumber);
  }

  void _createArtifact() {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    final blockId = _evidenceBlockId;
    if (database == null || revision == null || blockId == null) return;
    try {
      final document = database.createPrintableArtifactFromEvidence(
        revisionId: revision.id,
        evidenceBlockId: blockId,
        groupId: _groupId,
      );
      _groupId = document.artifact.groupId;
      _artifactId = document.artifact.id;
      _reload();
      if (mounted) setState(() => _error = null);
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _appendBlock() {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null ||
        revision == null ||
        _artifactId == null ||
        _evidenceBlockId == null)
      return;
    try {
      database.appendPrintableEvidenceBlock(
        revisionId: revision.id,
        artifactId: _artifactId!,
        evidenceBlockId: _evidenceBlockId!,
      );
      _reload();
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _saveMetadata() {
    final revision = workspace.selectedRevision;
    final database = workspace.database;
    if (revision == null || database == null || _artifactId == null) return;
    try {
      database.updatePrintableArtifactMetadata(
        datasetId: revision.datasetId,
        artifactId: _artifactId!,
        title: _title.text,
        exhibitNumber: _exhibit.text,
        caseNumber: _caseNumber.text,
      );
      _reload();
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _moveBlock(int joinId, int delta) {
    final revision = workspace.selectedRevision;
    final database = workspace.database;
    if (revision == null || database == null || _artifactId == null) return;
    try {
      database.movePrintableArtifactBlock(
        datasetId: revision.datasetId,
        artifactId: _artifactId!,
        joinId: joinId,
        delta: delta,
      );
      _reload();
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _removeBlock(int joinId) {
    final revision = workspace.selectedRevision;
    final database = workspace.database;
    if (revision == null || database == null || _artifactId == null) return;
    try {
      database.removePrintableArtifactBlock(
        datasetId: revision.datasetId,
        artifactId: _artifactId!,
        joinId: joinId,
      );
      _reload();
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      return const WorkstationPage(
        title: 'Document assembly',
        description:
            'Organize persisted evidence blocks into ordered, reviewable print artifacts.',
        child: EmptyWorkspaceState(
          icon: Icons.description_outlined,
          title: 'Document assembly requires a working corpus',
          message:
              'Select a ready working corpus on Corpus to organize document artifacts.',
        ),
      );
    }
    final evidence =
        workspace.transcriptController?.blocks ?? const <EvidenceBlock>[];
    return WorkstationPage(
      title: 'Document assembly',
      description:
          'Organize persisted evidence blocks into ordered, reviewable print artifacts.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            OperationalMessage(
              message: _error!,
              label: 'FAILED',
              tone: OperationalTone.failure,
            ),
            const SizedBox(height: 8),
          ],
          SectionSurface(
            padding: const EdgeInsets.all(12),
            backgroundColor: Theme.of(context).colorScheme.surfaceContainerLow,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SectionHeader(
                  title: 'Artifact controls',
                  description:
                      'Choose a collection and source evidence block before creating or appending.',
                  leading: Icon(Icons.account_tree_outlined, size: 19),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    DropdownButton<int>(
                      value: _groupId,
                      hint: const Text('No groups yet'),
                      items: _groups
                          .map(
                            (group) => DropdownMenuItem(
                              value: group.id,
                              child: Text(group.name),
                            ),
                          )
                          .toList(),
                      onChanged: _selectGroup,
                    ),
                    DropdownButton<int>(
                      value: _evidenceBlockId,
                      hint: const Text('Select evidence block'),
                      items: evidence
                          .map(
                            (block) => DropdownMenuItem(
                              value: block.id,
                              child: Text(
                                '${block.id}: ${block.title}',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: (value) =>
                          setState(() => _evidenceBlockId = value),
                    ),
                    FilledButton.icon(
                      onPressed: _evidenceBlockId == null
                          ? null
                          : _createArtifact,
                      icon: const Icon(Icons.note_add_outlined, size: 18),
                      label: const Text('Create artifact'),
                    ),
                    if (_document != null)
                      OutlinedButton.icon(
                        onPressed: _evidenceBlockId == null
                            ? null
                            : _appendBlock,
                        icon: const Icon(Icons.playlist_add, size: 18),
                        label: const Text('Append block'),
                      ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final artifactList = Card(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Padding(
                        padding: EdgeInsets.fromLTRB(12, 11, 12, 9),
                        child: SectionHeader(
                          title: 'Artifacts',
                          description: 'Persisted documents in this group.',
                          leading: Icon(Icons.description_outlined, size: 18),
                        ),
                      ),
                      const Divider(height: 1),
                      Expanded(
                        child: _artifacts.isEmpty
                            ? const Center(
                                child: Text('No persisted artifacts.'),
                              )
                            : ListView.separated(
                                itemCount: _artifacts.length,
                                separatorBuilder: (_, _) =>
                                    const Divider(height: 1),
                                itemBuilder: (context, index) {
                                  final artifact = _artifacts[index];
                                  return ListTile(
                                    selected: artifact.id == _artifactId,
                                    leading: const Icon(
                                      Icons.article_outlined,
                                      size: 19,
                                    ),
                                    title: Text(
                                      artifact.title.isEmpty
                                          ? 'Untitled artifact'
                                          : artifact.title,
                                    ),
                                    subtitle: Text(
                                      '${artifact.exhibitNumber} ${artifact.caseNumber}'
                                          .trim(),
                                    ),
                                    onTap: () => _selectArtifact(artifact.id),
                                  );
                                },
                              ),
                      ),
                    ],
                  ),
                );
                final preview = Card(
                  clipBehavior: Clip.antiAlias,
                  child: _document == null
                      ? const EmptyWorkspaceState(
                          icon: Icons.insert_drive_file_outlined,
                          title: 'No artifact selected',
                          message:
                              'Select or create an artifact to see Document preview.',
                        )
                      : _DocumentPreview(
                          document: _document!,
                          title: _title,
                          exhibit: _exhibit,
                          caseNumber: _caseNumber,
                          onSaveMetadata: _saveMetadata,
                          onMove: _moveBlock,
                          onRemove: _removeBlock,
                        ),
                );
                if (constraints.maxWidth >= 900) {
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      SizedBox(width: 300, child: artifactList),
                      const SizedBox(width: 10),
                      Expanded(child: preview),
                    ],
                  );
                }
                return Column(
                  children: [
                    SizedBox(height: 180, child: artifactList),
                    const SizedBox(height: 10),
                    Expanded(child: preview),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _DocumentPreview extends StatelessWidget {
  const _DocumentPreview({
    required this.document,
    required this.title,
    required this.exhibit,
    required this.caseNumber,
    required this.onSaveMetadata,
    required this.onMove,
    required this.onRemove,
  });

  final PrintableArtifactDocument document;
  final TextEditingController title;
  final TextEditingController exhibit;
  final TextEditingController caseNumber;
  final VoidCallback onSaveMetadata;
  final void Function(int, int) onMove;
  final void Function(int) onRemove;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      SectionHeader(
        title: 'Document preview',
        description: 'Group: ${document.groupName}',
        leading: const Icon(Icons.preview_outlined, size: 20),
      ),
      const SizedBox(height: 12),
      SectionSurface(
        backgroundColor: Theme.of(context).colorScheme.surfaceContainerLow,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'DOCUMENT METADATA',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.end,
              children: [
                SizedBox(
                  width: 240,
                  child: TextField(
                    controller: title,
                    decoration: const InputDecoration(labelText: 'Title'),
                  ),
                ),
                SizedBox(
                  width: 140,
                  child: TextField(
                    controller: exhibit,
                    decoration: const InputDecoration(
                      labelText: 'Exhibit number',
                    ),
                  ),
                ),
                SizedBox(
                  width: 180,
                  child: TextField(
                    controller: caseNumber,
                    decoration: const InputDecoration(labelText: 'Case number'),
                  ),
                ),
                FilledButton(
                  onPressed: onSaveMetadata,
                  child: const Text('Save metadata'),
                ),
              ],
            ),
          ],
        ),
      ),
      const Divider(height: 28),
      if (document.blocks.isEmpty)
        const Text('This artifact has no attached evidence blocks.')
      else
        ...document.blocks.asMap().entries.map(
          (entry) => _PreviewBlock(
            index: entry.key,
            block: entry.value,
            total: document.blocks.length,
            onMove: onMove,
            onRemove: onRemove,
          ),
        ),
    ],
  );
}

class _PreviewBlock extends StatelessWidget {
  const _PreviewBlock({
    required this.index,
    required this.block,
    required this.total,
    required this.onMove,
    required this.onRemove,
  });

  final int index;
  final PrintableArtifactBlock block;
  final int total;
  final void Function(int, int) onMove;
  final void Function(int) onRemove;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 10),
    color: Colors.white,
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${block.label}: ${block.evidence.title}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              IconButton(
                tooltip: 'Move up',
                onPressed: index == 0 ? null : () => onMove(block.joinId, -1),
                icon: const Icon(Icons.arrow_upward),
              ),
              IconButton(
                tooltip: 'Move down',
                onPressed: index == total - 1
                    ? null
                    : () => onMove(block.joinId, 1),
                icon: const Icon(Icons.arrow_downward),
              ),
              IconButton(
                tooltip: 'Remove attached block',
                style: IconButton.styleFrom(
                  foregroundColor: Theme.of(context).colorScheme.error,
                ),
                onPressed: () => onRemove(block.joinId),
                icon: const Icon(Icons.remove_circle_outline),
              ),
            ],
          ),
          if (block.evidence.summary.isNotEmpty) Text(block.evidence.summary),
          const SizedBox(height: 6),
          ...block.messages.map(
            (message) => Container(
              color: block.evidence.isRelevant(message)
                  ? const Color(0xffe5f1e9)
                  : const Color(0xfff4f6f7),
              padding: const EdgeInsets.all(10),
              margin: const EdgeInsets.only(bottom: 3),
              child: Text(
                '[${block.evidence.sections[message.id] ?? 'context'}] ${message.sender} · ${message.timestamp}\n${message.body}',
              ),
            ),
          ),
        ],
      ),
    ),
  );
}
