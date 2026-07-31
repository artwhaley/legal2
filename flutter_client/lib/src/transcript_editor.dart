import 'dart:collection';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'app_theme.dart';
import 'evw_database.dart';
import 'evw_models.dart';
import 'transcript_height_index.dart';
import 'splitter.dart';
import 'workstation_widgets.dart';

enum EvidenceBoundary { contextStart, relevantStart, relevantEnd, contextEnd }

extension EvidenceBoundaryLabel on EvidenceBoundary {
  String get label => switch (this) {
    EvidenceBoundary.contextStart => 'Context start',
    EvidenceBoundary.relevantStart => 'Relevant start',
    EvidenceBoundary.relevantEnd => 'Relevant end',
    EvidenceBoundary.contextEnd => 'Context end',
  };
}

class TranscriptAnnotation {
  const TranscriptAnnotation({
    required this.context,
    required this.relevant,
    required this.highlighted,
    required this.primary,
    required this.inActiveRelevantRange,
  });

  final bool context;
  final bool relevant;
  final bool highlighted;
  final bool primary;
  final bool inActiveRelevantRange;
}

class TranscriptDocumentController extends ChangeNotifier {
  TranscriptDocumentController({
    required this.database,
    required this.revision,
    this.onEvidenceMutation,
  }) : messageCount = revision.messages;

  final EvwDatabase database;
  final RevisionSummary revision;
  final VoidCallback? onEvidenceMutation;
  final int messageCount;
  List<EvidenceBlock> _blocks = [];
  final Set<int> _hiddenBlockIds = {};
  int? _activeBlockId;
  int _evidenceDataVersion = 0;
  bool _disposed = false;
  List<CategorySummary> _categories = const [];

  int get evidenceDataVersion => _evidenceDataVersion;

  List<EvidenceBlock> get blocks => List.unmodifiable(_blocks);
  List<CategorySummary> get categories => List.unmodifiable(_categories);
  int? get activeBlockId => _activeBlockId;
  EvidenceBlock? get activeBlock => _blockById(_activeBlockId);

  void reload() {
    _blocks = database.evidenceBlocks(revision.id);
    _categories = database.categories(revision.datasetId);
    if (_activeBlockId != null && _blockById(_activeBlockId) == null) {
      _activeBlockId = null;
    }
    _hiddenBlockIds.removeWhere(
      (id) => !_blocks.any((block) => block.id == id),
    );
    _notify(persisted: true);
  }

  EvidenceBlock? _blockById(int? id) {
    if (id == null) return null;
    for (final block in _blocks) {
      if (block.id == id) return block;
    }
    return null;
  }

  void _replaceBlock(EvidenceBlock block) {
    final index = _blocks.indexWhere((item) => item.id == block.id);
    if (index < 0) {
      _blocks.add(block);
    } else {
      _blocks[index] = block;
    }
  }

  void selectBlock(int? evidenceBlockId) {
    if (evidenceBlockId != null && _blockById(evidenceBlockId) == null) {
      throw StateError('Evidence block $evidenceBlockId is not loaded');
    }
    _activeBlockId = evidenceBlockId;
    if (evidenceBlockId != null) _hiddenBlockIds.remove(evidenceBlockId);
    _notify();
  }

  bool isHidden(int evidenceBlockId) =>
      _hiddenBlockIds.contains(evidenceBlockId);

  void reconcileActiveBlockForViewport({
    required int visibleStartOrdinal,
    required int visibleEndOrdinal,
    required int centerOrdinal,
  }) {
    if (visibleStartOrdinal > visibleEndOrdinal) {
      throw ArgumentError(
        'Visible transcript range is out of order: '
        '$visibleStartOrdinal..$visibleEndOrdinal',
      );
    }

    bool isVisible(EvidenceBlock block) =>
        !_hiddenBlockIds.contains(block.id) &&
        block.contextEndOrdinal >= visibleStartOrdinal &&
        block.contextStartOrdinal <= visibleEndOrdinal;

    final current = activeBlock;
    if (current != null && isVisible(current)) return;

    final candidates = _blocks.where(isVisible).toList();
    EvidenceBlock? next;
    if (candidates.isNotEmpty) {
      int distanceToSpan(EvidenceBlock block) {
        if (centerOrdinal < block.contextStartOrdinal) {
          return block.contextStartOrdinal - centerOrdinal;
        }
        if (centerOrdinal > block.contextEndOrdinal) {
          return centerOrdinal - block.contextEndOrdinal;
        }
        return 0;
      }

      candidates.sort((left, right) {
        final spanDistance = distanceToSpan(
          left,
        ).compareTo(distanceToSpan(right));
        if (spanDistance != 0) return spanDistance;
        final coreDistance = (left.coreOrdinal - centerOrdinal).abs().compareTo(
          (right.coreOrdinal - centerOrdinal).abs(),
        );
        if (coreDistance != 0) return coreDistance;
        return left.id.compareTo(right.id);
      });
      next = candidates.first;
    }

    final nextId = next?.id;
    if (_activeBlockId == nextId) return;
    _activeBlockId = nextId;
    _notify();
  }

  void setHidden(int evidenceBlockId, bool hidden) {
    if (_blockById(evidenceBlockId) == null) return;
    if (hidden) {
      _hiddenBlockIds.add(evidenceBlockId);
      if (_activeBlockId == evidenceBlockId) _activeBlockId = null;
    } else {
      _hiddenBlockIds.remove(evidenceBlockId);
    }
    _notify();
  }

  EvidenceBlock createAtOrdinal(
    int ordinal, {
    int? categoryId,
    String createdBy = 'transcript_editor',
  }) {
    final block = database.createEvidenceBlock(
      revisionId: revision.id,
      hitOrdinal: ordinal,
      categoryId: categoryId,
      createdBy: createdBy,
    );
    _replaceBlock(block);
    _activeBlockId = block.id;
    _hiddenBlockIds.remove(block.id);
    _notify(persisted: true);
    return block;
  }

  void saveMetadata(String title, String summary, {int? evidenceBlockId}) {
    final block = _blockById(evidenceBlockId) ?? activeBlock;
    if (block == null) throw StateError('Select an evidence block first');
    _replaceBlock(
      database.updateEvidenceMetadata(
        revisionId: revision.id,
        evidenceBlockId: block.id,
        title: title,
        summary: summary,
      ),
    );
    _notify(persisted: true);
  }

  void previewBoundary(EvidenceBoundary boundary, int candidateOrdinal) {
    final block = activeBlock;
    if (block == null) return;
    final candidate = database.nearestMessageInThread(
      revision.id,
      block.sourceThreadId,
      candidateOrdinal,
    );
    if (candidate == null) return;

    var contextStartOrdinal = block.contextStartOrdinal;
    var relevantStartOrdinal = block.relevantStartOrdinal;
    var relevantEndOrdinal = block.relevantEndOrdinal;
    var contextEndOrdinal = block.contextEndOrdinal;
    var contextStartId = block.contextStartMessageId;
    var relevantStartId = block.relevantStartMessageId;
    var relevantEndId = block.relevantEndMessageId;
    var contextEndId = block.contextEndMessageId;

    switch (boundary) {
      case EvidenceBoundary.contextStart:
        if (candidate.ordinal > relevantStartOrdinal) return;
        contextStartOrdinal = candidate.ordinal;
        contextStartId = candidate.id;
      case EvidenceBoundary.relevantStart:
        if (candidate.ordinal < contextStartOrdinal ||
            candidate.ordinal > block.coreOrdinal) {
          return;
        }
        relevantStartOrdinal = candidate.ordinal;
        relevantStartId = candidate.id;
      case EvidenceBoundary.relevantEnd:
        if (candidate.ordinal < block.coreOrdinal ||
            candidate.ordinal > contextEndOrdinal) {
          return;
        }
        relevantEndOrdinal = candidate.ordinal;
        relevantEndId = candidate.id;
      case EvidenceBoundary.contextEnd:
        if (candidate.ordinal < relevantEndOrdinal) return;
        contextEndOrdinal = candidate.ordinal;
        contextEndId = candidate.id;
    }
    if (contextStartOrdinal == contextEndOrdinal) return;

    _replaceBlock(
      block.copyWith(
        contextStartMessageId: contextStartId,
        relevantStartMessageId: relevantStartId,
        relevantEndMessageId: relevantEndId,
        contextEndMessageId: contextEndId,
        contextStartOrdinal: contextStartOrdinal,
        relevantStartOrdinal: relevantStartOrdinal,
        relevantEndOrdinal: relevantEndOrdinal,
        contextEndOrdinal: contextEndOrdinal,
      ),
    );
    _notify();
  }

  void persistBoundaryEdit() {
    final block = activeBlock;
    if (block == null) return;
    try {
      _replaceBlock(
        database.replaceEvidenceRange(revisionId: revision.id, block: block),
      );
      _notify(persisted: true);
    } catch (_) {
      reload();
      rethrow;
    }
  }

  void setPrimaryMessage(String messageId) {
    final block = activeBlock;
    if (block == null) return;
    _replaceBlock(
      database.updateCoreMessage(
        revisionId: revision.id,
        evidenceBlockId: block.id,
        messageId: messageId,
      ),
    );
    _notify(persisted: true);
  }

  void toggleHighlight(String messageId) {
    final block = activeBlock;
    if (block == null) return;
    _replaceBlock(
      database.toggleEvidenceHighlight(
        revisionId: revision.id,
        evidenceBlockId: block.id,
        messageId: messageId,
      ),
    );
    _notify(persisted: true);
  }

  void deleteBlock(int evidenceBlockId) {
    final block = _blockById(evidenceBlockId);
    if (block == null) {
      throw StateError('Evidence block $evidenceBlockId is not loaded');
    }
    database.deleteEvidenceBlock(
      revisionId: revision.id,
      evidenceBlockId: evidenceBlockId,
    );
    _hiddenBlockIds.remove(block.id);
    if (_activeBlockId == evidenceBlockId) _activeBlockId = null;
    _blocks.removeWhere((item) => item.id == block.id);
    _notify(persisted: true);
  }

  void moveBlockToCategory({
    required int evidenceBlockId,
    required int categoryId,
  }) {
    final updated = database.moveEvidenceBlock(
      revisionId: revision.id,
      evidenceBlockId: evidenceBlockId,
      categoryId: categoryId,
    );
    _replaceBlock(updated);
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
  }

  CategorySummary createCategory(String name) {
    final created = database.createCategory(
      datasetId: revision.datasetId,
      name: name,
    );
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
    return created;
  }

  CategorySummary renameCategory({
    required int categoryId,
    required String name,
  }) {
    final renamed = database.renameCategory(
      datasetId: revision.datasetId,
      categoryId: categoryId,
      name: name,
    );
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
    return renamed;
  }

  CategorySummary setCategoryCollapsed({
    required int categoryId,
    required bool isCollapsed,
  }) {
    final updated = database.setCategoryCollapsed(
      datasetId: revision.datasetId,
      categoryId: categoryId,
      isCollapsed: isCollapsed,
    );
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
    return updated;
  }

  void deleteCategory(int categoryId) {
    database.deleteCategory(
      datasetId: revision.datasetId,
      categoryId: categoryId,
    );
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
  }

  void mergeCategories({
    required int sourceCategoryId,
    required int destinationCategoryId,
  }) {
    database.mergeCategories(
      datasetId: revision.datasetId,
      sourceCategoryId: sourceCategoryId,
      destinationCategoryId: destinationCategoryId,
    );
    _categories = database.categories(revision.datasetId);
    _notify(persisted: true);
  }

  TranscriptAnnotation annotationFor(TranscriptMessage message) {
    var context = false;
    var relevant = false;
    var highlighted = false;
    var primary = false;
    var activeRelevant = false;
    for (final block in _blocks) {
      if (_hiddenBlockIds.contains(block.id) || !block.contains(message)) {
        continue;
      }
      if (block.isRelevant(message)) {
        relevant = true;
        if (block.id == _activeBlockId) activeRelevant = true;
      } else {
        context = true;
      }
      highlighted =
          highlighted || block.highlightedMessageIds.contains(message.id);
      primary = primary || block.coreMessageId == message.id;
    }
    return TranscriptAnnotation(
      context: context,
      relevant: relevant,
      highlighted: highlighted,
      primary: primary,
      inActiveRelevantRange: activeRelevant,
    );
  }

  void _notify({bool persisted = false}) {
    if (_disposed) return;
    if (persisted) {
      _evidenceDataVersion += 1;
      onEvidenceMutation?.call();
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _blocks = [];
    _hiddenBlockIds.clear();
    _activeBlockId = null;
    super.dispose();
  }
}

class VirtualTranscriptView extends StatefulWidget {
  const VirtualTranscriptView({
    super.key,
    required this.controller,
    this.onError,
    this.onViewportChanged,
    this.viewportActivationEnabled = true,
  });

  final TranscriptDocumentController controller;
  final ValueChanged<Object>? onError;
  final VoidCallback? onViewportChanged;
  final bool viewportActivationEnabled;

  @override
  State<VirtualTranscriptView> createState() => VirtualTranscriptViewState();
}

class VirtualTranscriptViewState extends State<VirtualTranscriptView> {
  static const _pageSize = 80;
  static const _maxCachedPages = 10;
  static const _overscan = 10;

  final ScrollController _scrollController = ScrollController();
  final GlobalKey _documentKey = GlobalKey();
  final LinkedHashMap<int, List<TranscriptMessage>> _pages =
      LinkedHashMap<int, List<TranscriptMessage>>();
  late TranscriptHeightIndex _heightIndex;
  double _viewportHeight = 600;
  double _contentWidth = 700;
  int _visibleStart = 0;
  int _visibleEnd = 0;
  int? _lastDragOrdinal;
  bool _viewportActivationScheduled = false;

  int get visibleStart => _visibleStart;
  int get visibleEnd => _visibleEnd;
  int get cachedMessageCount =>
      _pages.values.fold(0, (total, page) => total + page.length);
  int get measuredHeightCount => _heightIndex.measuredCount;

  @override
  void initState() {
    super.initState();
    _heightIndex = TranscriptHeightIndex(widget.controller.messageCount);
    _scrollController.addListener(_onScroll);
    widget.controller.addListener(_onControllerChanged);
  }

  @override
  void didUpdateWidget(VirtualTranscriptView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_onControllerChanged);
      widget.controller.addListener(_onControllerChanged);
      _pages.clear();
      _heightIndex = TranscriptHeightIndex(widget.controller.messageCount);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) _scrollController.jumpTo(0);
      });
      if (widget.viewportActivationEnabled) _scheduleViewportActivation();
    } else if (!oldWidget.viewportActivationEnabled &&
        widget.viewportActivationEnabled) {
      _scheduleViewportActivation();
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    _scrollController
      ..removeListener(_onScroll)
      ..dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    if (!mounted) return;
    setState(() {});
    _scheduleViewportActivation();
  }

  void _onScroll() {
    if (!mounted) return;
    setState(() {});
    _scheduleViewportActivation();
    widget.onViewportChanged?.call();
  }

  void _scheduleViewportActivation() {
    if (!widget.viewportActivationEnabled) return;
    if (_viewportActivationScheduled) return;
    _viewportActivationScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _viewportActivationScheduled = false;
      if (!mounted || widget.controller.messageCount == 0) return;
      final offset = _scrollController.hasClients
          ? _scrollController.offset
          : 0.0;
      final visibleStart = _heightIndex.ordinalForOffset(offset);
      final visibleEnd = _heightIndex.ordinalForOffset(
        offset + _viewportHeight,
      );
      final center = _heightIndex.ordinalForOffset(
        offset + (_viewportHeight / 2),
      );
      widget.controller.reconcileActiveBlockForViewport(
        visibleStartOrdinal: visibleStart,
        visibleEndOrdinal: visibleEnd,
        centerOrdinal: center,
      );
    });
  }

  TranscriptMessage? _messageAt(int ordinal) {
    if (ordinal < 0 || ordinal >= widget.controller.messageCount) return null;
    final pageStart = (ordinal ~/ _pageSize) * _pageSize;
    var page = _pages.remove(pageStart);
    if (page == null) {
      page = widget.controller.database.transcript(
        widget.controller.revision.id,
        limit: _pageSize,
        offset: pageStart,
      );
    }
    _pages[pageStart] = page;
    while (_pages.length > _maxCachedPages) {
      _pages.remove(_pages.keys.first);
    }
    final index = ordinal - pageStart;
    return index < page.length ? page[index] : null;
  }

  double _measureMessage(TranscriptMessage message, double width) {
    final bodyWidth = math.max(180.0, width - 132);
    final sender = TextPainter(
      text: TextSpan(
        text: message.sender,
        style: const TextStyle(
          fontSize: 13.5,
          fontWeight: FontWeight.w600,
          height: 1.25,
        ),
      ),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: bodyWidth);
    final body = TextPainter(
      text: TextSpan(
        text: message.body,
        style: const TextStyle(fontSize: 14.5, height: 1.48),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: bodyWidth);
    return math.max(86, 18 + sender.height + 7 + body.height + 34);
  }

  List<Widget> _visibleMessages(double width) {
    if (widget.controller.messageCount == 0) return const [];
    final offset = _scrollController.hasClients
        ? _scrollController.offset
        : 0.0;
    final first = _heightIndex.ordinalForOffset(offset);
    final last = _heightIndex.ordinalForOffset(offset + _viewportHeight);
    final start = math.max(0, first - _overscan);
    final end = math.min(widget.controller.messageCount, last + _overscan + 1);
    _visibleStart = start;
    _visibleEnd = math.max(start, end - 1);

    final messageWidth = math.min(960.0, math.max(260.0, width - 48));
    final horizontalInset = math.max(24.0, (width - messageWidth) / 2);
    final messages = <TranscriptMessage>[];
    for (var ordinal = start; ordinal < end; ordinal++) {
      final message = _messageAt(ordinal);
      if (message != null) messages.add(message);
    }
    for (final message in messages) {
      _heightIndex.setHeight(
        message.ordinal,
        _measureMessage(message, messageWidth),
      );
    }
    return messages.map((message) {
      final annotation = widget.controller.annotationFor(message);
      return Positioned(
        top: _heightIndex.offsetForOrdinal(message.ordinal),
        left: horizontalInset,
        right: horizontalInset,
        height: _heightIndex.heightAt(message.ordinal),
        child: _TranscriptMessageView(
          message: message,
          annotation: annotation,
          onSetPrimary: annotation.inActiveRelevantRange
              ? () => _guard(() {
                  widget.controller.setPrimaryMessage(message.id);
                })
              : null,
          onToggleHighlight: annotation.inActiveRelevantRange
              ? () => _guard(() {
                  widget.controller.toggleHighlight(message.id);
                })
              : null,
        ),
      );
    }).toList();
  }

  List<Widget> _boundaryHandles() {
    final block = widget.controller.activeBlock;
    if (block == null) return const [];
    final positions = <EvidenceBoundary, double>{
      EvidenceBoundary.contextStart: _heightIndex.offsetForOrdinal(
        block.contextStartOrdinal,
      ),
      EvidenceBoundary.relevantStart: _heightIndex.offsetForOrdinal(
        block.relevantStartOrdinal,
      ),
      EvidenceBoundary.relevantEnd: _heightIndex.offsetForOrdinal(
        block.relevantEndOrdinal + 1,
      ),
      EvidenceBoundary.contextEnd: _heightIndex.offsetForOrdinal(
        block.contextEndOrdinal + 1,
      ),
    };
    return positions.entries
        .map(
          (entry) => Positioned(
            top: entry.value - 10,
            left: 2,
            right: 2,
            height: 20,
            child: _BoundaryHandle(
              boundary: entry.key,
              onDragStart: () {
                _lastDragOrdinal = null;
              },
              onDragUpdate: (globalPosition) {
                final box =
                    _documentKey.currentContext?.findRenderObject()
                        as RenderBox?;
                if (box == null) return;
                final contentY = box.globalToLocal(globalPosition).dy;
                final ordinal = _heightIndex.ordinalForOffset(contentY);
                if (_lastDragOrdinal == ordinal) return;
                _lastDragOrdinal = ordinal;
                widget.controller.previewBoundary(entry.key, ordinal);
              },
              onDragEnd: () => _guard(widget.controller.persistBoundaryEdit),
            ),
          ),
        )
        .toList();
  }

  void _guard(VoidCallback operation) {
    try {
      operation();
    } catch (error) {
      widget.onError?.call(error);
    }
  }

  int? viewportCenterOrdinal() {
    if (widget.controller.messageCount == 0) return null;
    final offset = _scrollController.hasClients
        ? _scrollController.offset
        : 0.0;
    return _heightIndex.ordinalForOffset(offset + (_viewportHeight / 2));
  }

  bool scrollToOrdinal(int ordinal) {
    if (widget.controller.messageCount == 0) return false;
    final target = ordinal.clamp(0, widget.controller.messageCount - 1);
    void jump() {
      if (!_scrollController.hasClients) return;
      final maximum = _scrollController.position.maxScrollExtent;
      final offset =
          (_heightIndex.offsetForOrdinal(target) -
                  (_viewportHeight / 2) +
                  (_heightIndex.heightAt(target) / 2))
              .clamp(0, maximum);
      _scrollController.jumpTo(offset.toDouble());
    }

    jump();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) jump();
    });
    return true;
  }

  bool scrollToMessage(String messageId) {
    final ordinal = widget.controller.database.ordinalForMessage(
      widget.controller.revision.id,
      messageId,
    );
    return ordinal == null ? false : scrollToOrdinal(ordinal);
  }

  void reconcileViewport() => _scheduleViewportActivation();

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      _viewportHeight = constraints.maxHeight;
      final nextWidth = constraints.maxWidth;
      if ((_contentWidth - nextWidth).abs() > 1) {
        final anchor = viewportCenterOrdinal();
        _contentWidth = nextWidth;
        _heightIndex.invalidate();
        if (anchor != null) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) scrollToOrdinal(anchor);
          });
        }
      }
      final children = <Widget>[
        ..._visibleMessages(nextWidth),
        ..._boundaryHandles(),
      ];
      final messageWidth = math.min(960.0, math.max(260.0, nextWidth - 48));
      final messageInset = math.max(24.0, (nextWidth - messageWidth) / 2);
      final markerInset = math.max(2.0, messageInset - 22);
      _scheduleViewportActivation();
      return DecoratedBox(
        decoration: const BoxDecoration(color: Color(0xffedf0f1)),
        child: Stack(
          children: [
            Scrollbar(
              controller: _scrollController,
              thumbVisibility: true,
              interactive: true,
              child: SingleChildScrollView(
                controller: _scrollController,
                child: SizedBox(
                  key: _documentKey,
                  width: constraints.maxWidth,
                  height: math.max(
                    constraints.maxHeight,
                    _heightIndex.totalHeight + 24,
                  ),
                  child: Stack(clipBehavior: Clip.hardEdge, children: children),
                ),
              ),
            ),
            IgnorePointer(
              child: Align(
                alignment: Alignment.center,
                child: Padding(
                  padding: EdgeInsets.only(
                    left: markerInset,
                    right: markerInset,
                  ),
                  child: const Row(
                    children: [
                      Icon(
                        Icons.chevron_right,
                        size: 28,
                        color: Color(0xe028516b),
                      ),
                      Spacer(),
                      Icon(
                        Icons.chevron_left,
                        size: 28,
                        color: Color(0xe028516b),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    },
  );
}

class _TranscriptMessageView extends StatelessWidget {
  const _TranscriptMessageView({
    required this.message,
    required this.annotation,
    this.onSetPrimary,
    this.onToggleHighlight,
  });

  final TranscriptMessage message;
  final TranscriptAnnotation annotation;
  final VoidCallback? onSetPrimary;
  final VoidCallback? onToggleHighlight;

  @override
  Widget build(BuildContext context) {
    final background = annotation.highlighted
        ? const Color(0xfffff4c7)
        : annotation.relevant
        ? const Color(0xffe5f1e9)
        : annotation.context
        ? const Color(0xffedf0f2)
        : const Color(0xfffbfcfc);
    final accent = annotation.highlighted
        ? const Color(0xffa87a12)
        : annotation.relevant
        ? const Color(0xff3f7656)
        : annotation.context
        ? const Color(0xff89969e)
        : const Color(0xffd8dfe2);
    final subdued = annotation.context && !annotation.relevant;
    return Container(
      decoration: BoxDecoration(
        color: background,
        border: Border(
          left: BorderSide(color: accent, width: annotation.primary ? 4 : 3),
          bottom: const BorderSide(color: Color(0xffd8dfe2)),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 11, 10, 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          message.sender,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w600,
                            color: subdued
                                ? const Color(0xff617079)
                                : AppTheme.ink,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        message.timestamp,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppTheme.mutedInk,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 7),
                  SelectableText(
                    message.body,
                    style: TextStyle(
                      fontSize: 14.5,
                      height: 1.48,
                      fontWeight: annotation.relevant || annotation.highlighted
                          ? FontWeight.w500
                          : FontWeight.normal,
                      color: subdued ? const Color(0xff617079) : AppTheme.ink,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${message.threadTitle} · message ${message.ordinal + 1}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 10,
                      color: Color(0xff6e7d86),
                      letterSpacing: 0.15,
                    ),
                  ),
                ],
              ),
            ),
            if (onSetPrimary != null || onToggleHighlight != null)
              SizedBox(
                width: 82,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Tooltip(
                      message: 'Set as the block’s primary message',
                      child: IconButton(
                        visualDensity: VisualDensity.compact,
                        onPressed: onSetPrimary,
                        icon: Icon(
                          annotation.primary
                              ? Icons.radio_button_checked
                              : Icons.radio_button_unchecked,
                          color: annotation.primary ? AppTheme.navy : null,
                        ),
                      ),
                    ),
                    Tooltip(
                      message: 'Toggle highlight in this evidence block',
                      child: IconButton(
                        visualDensity: VisualDensity.compact,
                        onPressed: onToggleHighlight,
                        icon: Icon(
                          annotation.highlighted
                              ? Icons.star
                              : Icons.star_border,
                          color: annotation.highlighted
                              ? const Color(0xff936b0e)
                              : null,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _BoundaryHandle extends StatelessWidget {
  const _BoundaryHandle({
    required this.boundary,
    required this.onDragStart,
    required this.onDragUpdate,
    required this.onDragEnd,
  });

  final EvidenceBoundary boundary;
  final VoidCallback onDragStart;
  final ValueChanged<Offset> onDragUpdate;
  final VoidCallback onDragEnd;

  @override
  Widget build(BuildContext context) => MouseRegion(
    cursor: SystemMouseCursors.resizeUpDown,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onVerticalDragStart: (_) => onDragStart(),
      onVerticalDragUpdate: (details) => onDragUpdate(details.globalPosition),
      onVerticalDragEnd: (_) => onDragEnd(),
      child: Row(
        children: [
          Container(
            width: 112,
            height: 20,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: const Color(0xfff7fafb),
              border: Border.all(color: AppTheme.navy),
              borderRadius: BorderRadius.circular(3),
            ),
            child: Text(
              boundary.label,
              style: const TextStyle(
                fontSize: 11,
                color: AppTheme.navy,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 6),
          const Expanded(
            child: Divider(color: AppTheme.navy, thickness: 2, height: 2),
          ),
          const SizedBox(width: 20),
        ],
      ),
    ),
  );
}

class TranscriptEvidenceEditor extends StatefulWidget {
  const TranscriptEvidenceEditor({
    super.key,
    required this.database,
    required this.revision,
    this.controller,
    this.isPageActive = true,
    this.sidebarWidth,
    this.onSidebarWidthChanged,
  });

  final EvwDatabase database;
  final RevisionSummary revision;
  final TranscriptDocumentController? controller;
  final bool isPageActive;
  final double? sidebarWidth;
  final ValueChanged<double>? onSidebarWidthChanged;

  @override
  State<TranscriptEvidenceEditor> createState() =>
      TranscriptEvidenceEditorState();
}

class TranscriptEvidenceEditorState extends State<TranscriptEvidenceEditor> {
  final GlobalKey<VirtualTranscriptViewState> _transcriptKey = GlobalKey();
  late TranscriptDocumentController _controller;
  bool _ownsController = false;
  final TextEditingController _title = TextEditingController();
  final TextEditingController _summary = TextEditingController();
  int? _metadataBlockId;
  int? _selectedSidebarBlockId;
  int? _selectedCategoryId;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initializeController();
  }

  @override
  void didUpdateWidget(TranscriptEvidenceEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.database != widget.database ||
        oldWidget.revision.id != widget.revision.id ||
        oldWidget.controller != widget.controller) {
      _controller.removeListener(_onControllerChanged);
      if (_ownsController) _controller.dispose();
      _initializeController();
    } else if (!oldWidget.isPageActive && widget.isPageActive) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _transcriptKey.currentState?.reconcileViewport();
      });
    }
  }

  void _initializeController() {
    _ownsController = widget.controller == null;
    _controller =
        widget.controller ??
        (TranscriptDocumentController(
          database: widget.database,
          revision: widget.revision,
        )..reload());
    _controller.addListener(_onControllerChanged);
    _syncMetadataFields();
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    if (_ownsController) _controller.dispose();
    _title.dispose();
    _summary.dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    _syncMetadataFields();
    if (mounted) setState(() {});
  }

  void _syncMetadataFields() {
    final selectedId = _selectedSidebarBlockId;
    final block = selectedId == null ? null : _blockById(selectedId);
    if (selectedId != null && block == null) {
      _selectedSidebarBlockId = null;
      _selectedCategoryId = null;
    }
    if (block?.id == _metadataBlockId) return;
    _metadataBlockId = block?.id;
    _title.text = block?.title ?? '';
    _summary.text = block?.summary ?? '';
  }

  EvidenceBlock? _blockById(int? blockId) {
    if (blockId == null) return null;
    final matches = _controller.blocks.where((block) => block.id == blockId);
    return matches.isEmpty ? null : matches.first;
  }

  CategorySummary? _categoryById(int? categoryId) {
    if (categoryId == null) return null;
    final matches = _controller.categories.where(
      (category) => category.id == categoryId,
    );
    return matches.isEmpty ? null : matches.first;
  }

  int _creationCategoryId() {
    final selectedBlock = _blockById(_selectedSidebarBlockId);
    final categoryId = _selectedCategoryId ?? selectedBlock?.categoryId;
    if (categoryId != null && _categoryById(categoryId) != null) {
      return categoryId;
    }
    final uncategorizedMatches = _controller.categories.where(
      (category) => category.name.toLowerCase() == 'uncategorized',
    );
    final uncategorized = uncategorizedMatches.isEmpty
        ? null
        : uncategorizedMatches.first;
    if (uncategorized == null) {
      throw StateError('The selected dataset has no Uncategorized category');
    }
    return uncategorized.id;
  }

  void _selectSidebarCategory(int categoryId) {
    setState(() {
      _selectedCategoryId = categoryId;
      _selectedSidebarBlockId = null;
    });
    _syncMetadataFields();
  }

  void _selectSidebarBlock(EvidenceBlock block) {
    setState(() {
      _selectedSidebarBlockId = block.id;
      _selectedCategoryId = block.categoryId;
    });
    _syncMetadataFields();
    revealEvidenceBlock(block.id);
  }

  void _run(VoidCallback operation) {
    try {
      operation();
      setState(() => _error = null);
    } catch (error) {
      setState(() => _error = '$error');
    }
  }

  void _createAtCenter() {
    final ordinal = _transcriptKey.currentState?.viewportCenterOrdinal();
    if (ordinal == null) return;
    _run(() {
      final block = _controller.createAtOrdinal(
        ordinal,
        categoryId: _creationCategoryId(),
      );
      _selectedSidebarBlockId = block.id;
      _selectedCategoryId = block.categoryId;
      _syncMetadataFields();
      _transcriptKey.currentState?.scrollToOrdinal(block.coreOrdinal);
    });
  }

  void revealEvidenceBlock(int evidenceBlockId) {
    _run(() {
      _controller.selectBlock(evidenceBlockId);
      final block = _controller.activeBlock;
      if (block != null) {
        _transcriptKey.currentState?.scrollToOrdinal(block.coreOrdinal);
      }
    });
  }

  bool focusMessage(String messageId) =>
      _transcriptKey.currentState?.scrollToMessage(messageId) ?? false;

  EvidenceBlock? createEvidenceBlockForMessage(
    String messageId, {
    String createdBy = 'transcript_editor',
  }) {
    final ordinal = widget.database.ordinalForMessage(
      widget.revision.id,
      messageId,
    );
    if (ordinal == null) return null;
    EvidenceBlock? result;
    _run(() {
      result = _controller.createAtOrdinal(
        ordinal,
        categoryId: _creationCategoryId(),
        createdBy: createdBy,
      );
      _selectedSidebarBlockId = result!.id;
      _selectedCategoryId = result!.categoryId;
      _syncMetadataFields();
      _transcriptKey.currentState?.scrollToOrdinal(ordinal);
    });
    return result;
  }

  Future<void> _confirmDeleteBlock(EvidenceBlock block) async {
    final blockId = block.id;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete evidence block?'),
        content: Text(
          'Delete “${block.title}” and its evidence markup?\n\n'
          'This does not delete transcript messages and cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(dialogContext).colorScheme.error,
              foregroundColor: Theme.of(dialogContext).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete block'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      _run(() {
        _controller.deleteBlock(blockId);
        if (_selectedSidebarBlockId == blockId) {
          _selectedSidebarBlockId = null;
          _selectedCategoryId = null;
          _syncMetadataFields();
        }
      });
    }
  }

  Future<void> _deleteActiveBlock() async {
    final block = _blockById(_selectedSidebarBlockId);
    if (block != null) await _confirmDeleteBlock(block);
  }

  Future<String?> _categoryNameDialog({
    required String title,
    required String action,
    String initial = '',
  }) async {
    final field = TextEditingController(text: initial);
    try {
      return await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(title),
          content: TextField(
            controller: field,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Name'),
            onSubmitted: (value) => Navigator.pop(dialogContext, value),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, field.text),
              child: Text(action),
            ),
          ],
        ),
      );
    } finally {
      field.dispose();
    }
  }

  Future<void> _createCategory() async {
    final name = await _categoryNameDialog(
      title: 'New category',
      action: 'Create',
    );
    if (!mounted || name == null) return;
    _run(() {
      final created = _controller.createCategory(name);
      setState(() {
        _selectedCategoryId = created.id;
        _selectedSidebarBlockId = null;
      });
      _syncMetadataFields();
    });
  }

  Future<void> _renameCategory(CategorySummary category) async {
    final name = await _categoryNameDialog(
      title: 'Rename category',
      action: 'Save',
      initial: category.name,
    );
    if (!mounted || name == null) return;
    _run(() => _controller.renameCategory(categoryId: category.id, name: name));
  }

  Future<void> _deleteCategory(CategorySummary category) async {
    if (category.evidenceCount != 0) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete category?'),
        content: Text('Delete category “${category.name}”?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(dialogContext).colorScheme.error,
              foregroundColor: Theme.of(dialogContext).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete category'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    _run(() {
      _controller.deleteCategory(category.id);
      if (_selectedCategoryId == category.id) _selectedCategoryId = null;
    });
  }

  Future<void> _mergeCategory(CategorySummary source) async {
    final destinations = _controller.categories
        .where((category) => category.id != source.id)
        .toList();
    if (destinations.isEmpty) return;
    var destinationId = destinations.first.id;
    final selectedDestination = await showDialog<int>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Merge category'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Merge “${source.name}” into the destination category? '
                '${source.evidenceCount} evidence blocks will move.',
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                value: destinationId,
                decoration: const InputDecoration(labelText: 'Destination'),
                items: destinations
                    .map(
                      (category) => DropdownMenuItem(
                        value: category.id,
                        child: Text(category.name),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  if (value != null)
                    setDialogState(() => destinationId = value);
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, destinationId),
              child: const Text('Merge'),
            ),
          ],
        ),
      ),
    );
    if (selectedDestination == null || !mounted) return;
    _run(() {
      _controller.mergeCategories(
        sourceCategoryId: source.id,
        destinationCategoryId: selectedDestination,
      );
      if (_selectedCategoryId == source.id) {
        _selectedCategoryId = selectedDestination;
      }
    });
  }

  void _moveBlockToCategory(int blockId, int categoryId) {
    final block = _blockById(blockId);
    if (block == null || block.categoryId == categoryId) return;
    _run(() {
      _controller.moveBlockToCategory(
        evidenceBlockId: blockId,
        categoryId: categoryId,
      );
      final destination = _categoryById(categoryId);
      if (destination?.isCollapsed == true) {
        _controller.setCategoryCollapsed(
          categoryId: categoryId,
          isCollapsed: false,
        );
      }
      setState(() {
        _selectedSidebarBlockId = blockId;
        _selectedCategoryId = categoryId;
      });
      _syncMetadataFields();
    });
  }

  Widget _categoryInspector() {
    final selected = _blockById(_selectedSidebarBlockId);
    final blocksByCategory = <int, List<EvidenceBlock>>{};
    for (final block in _controller.blocks) {
      blocksByCategory.putIfAbsent(block.categoryId, () => []).add(block);
    }
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SectionHeader(
              title: 'Evidence blocks',
              leading: const Icon(Icons.bookmarks_outlined, size: 19),
              trailing: OutlinedButton.icon(
                onPressed: _createCategory,
                icon: const Icon(Icons.create_new_folder_outlined, size: 17),
                label: const Text('New category'),
              ),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: _controller.categories.isEmpty
                  ? const Center(child: Text('No evidence categories yet.'))
                  : ListView(
                      children: [
                        for (final category in _controller.categories)
                          _categoryTree(
                            category,
                            blocksByCategory[category.id] ?? const [],
                          ),
                      ],
                    ),
            ),
            const Divider(),
            if (selected != null) ...[
              TextField(
                controller: _title,
                decoration: const InputDecoration(labelText: 'Title'),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _summary,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Summary',
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: () => _run(
                  () => _controller.saveMetadata(
                    _title.text,
                    _summary.text,
                    evidenceBlockId: selected.id,
                  ),
                ),
                child: const Text('Save title and summary'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _categoryTree(CategorySummary category, List<EvidenceBlock> blocks) =>
      DragTarget<int>(
        onWillAcceptWithDetails: (_) => true,
        onAcceptWithDetails: (details) =>
            _moveBlockToCategory(details.data, category.id),
        builder: (context, candidates, rejected) {
          final isSelected = _selectedCategoryId == category.id;
          final isHovering = candidates.isNotEmpty;
          return Container(
            margin: const EdgeInsets.only(bottom: 5),
            decoration: BoxDecoration(
              color: isHovering
                  ? Theme.of(
                      context,
                    ).colorScheme.primaryContainer.withValues(alpha: 0.45)
                  : null,
              border: Border.all(
                color: isHovering
                    ? Theme.of(context).colorScheme.primary
                    : Theme.of(context).colorScheme.outlineVariant,
              ),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ListTile(
                  dense: true,
                  selected: isSelected,
                  leading: IconButton(
                    tooltip: category.isCollapsed
                        ? 'Expand category'
                        : 'Collapse category',
                    onPressed: () => _run(
                      () => _controller.setCategoryCollapsed(
                        categoryId: category.id,
                        isCollapsed: !category.isCollapsed,
                      ),
                    ),
                    icon: Icon(
                      category.isCollapsed
                          ? Icons.chevron_right
                          : Icons.expand_more,
                    ),
                  ),
                  title: Text(category.name),
                  subtitle: Text('${category.evidenceCount} evidence blocks'),
                  onTap: () => _selectSidebarCategory(category.id),
                  trailing: _categoryMenu(category),
                ),
                if (!category.isCollapsed) ...blocks.map(_sidebarBlockRow),
              ],
            ),
          );
        },
      );

  Widget? _categoryMenu(CategorySummary category) {
    if (category.name.toLowerCase() == 'uncategorized') return null;
    final canDelete = category.evidenceCount == 0;
    return PopupMenuButton<String>(
      tooltip: 'Category actions',
      onSelected: (action) {
        switch (action) {
          case 'rename':
            _renameCategory(category);
          case 'delete':
            _deleteCategory(category);
          case 'merge':
            _mergeCategory(category);
        }
      },
      itemBuilder: (context) => [
        const PopupMenuItem(value: 'rename', child: Text('Rename category')),
        if (canDelete)
          const PopupMenuItem(value: 'delete', child: Text('Delete category')),
        const PopupMenuItem(value: 'merge', child: Text('Merge into...')),
      ],
    );
  }

  Widget _sidebarBlockRow(EvidenceBlock block) {
    final hidden = _controller.isHidden(block.id);
    final selected = _selectedSidebarBlockId == block.id;
    return Draggable<int>(
      data: block.id,
      feedback: Material(
        elevation: 4,
        child: SizedBox(
          width: 280,
          child: ListTile(
            dense: true,
            title: Text(
              block.title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
      ),
      child: GestureDetector(
        onSecondaryTapUp: (_) => _showBlockContextMenu(block),
        child: ListTile(
          dense: true,
          selected: selected,
          contentPadding: const EdgeInsets.only(left: 8, right: 4),
          leading: const Icon(Icons.drag_indicator, size: 18),
          title: Text(
            block.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          subtitle: Text('${block.messageIds.length} messages'),
          onTap: () => _selectSidebarBlock(block),
          trailing: IconButton(
            tooltip: hidden
                ? 'Show this blockâ€™s transcript markup'
                : 'Hide this blockâ€™s transcript markup',
            onPressed: () => _controller.setHidden(block.id, !hidden),
            icon: Icon(hidden ? Icons.visibility_off : Icons.visibility),
          ),
        ),
      ),
    );
  }

  Future<void> _showBlockContextMenu(EvidenceBlock block) async {
    final action = await showMenu<String>(
      context: context,
      position: const RelativeRect.fromLTRB(180, 240, 20, 20),
      items: const [
        PopupMenuItem(value: 'delete', child: Text('Delete block')),
      ],
    );
    if (action == 'delete' && mounted) await _confirmDeleteBlock(block);
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: OperationalMessage(
            message: _error!,
            label: 'FAILED',
            tone: OperationalTone.failure,
            trailing: TextButton(
              onPressed: () => setState(() => _error = null),
              child: const Text('Dismiss'),
            ),
          ),
        ),
      Expanded(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final transcript = Card(
              clipBehavior: Clip.antiAlias,
              margin: EdgeInsets.zero,
              child: VirtualTranscriptView(
                key: _transcriptKey,
                controller: _controller,
                viewportActivationEnabled: widget.isPageActive,
                onError: (error) => setState(() => _error = '$error'),
              ),
            );
            final inspector = _categoryInspector();
            final sidebar = Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(child: inspector),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: widget.revision.status == 'ready'
                            ? _createAtCenter
                            : null,
                        icon: const Icon(Icons.add, size: 18),
                        label: const Text('New block at center'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _selectedSidebarBlockId == null
                            ? null
                            : () {
                                final block = _blockById(
                                  _selectedSidebarBlockId,
                                );
                                if (block != null) _confirmDeleteBlock(block);
                              },
                        icon: const Icon(Icons.delete_outline, size: 18),
                        label: const Text('Delete selected'),
                      ),
                    ),
                  ],
                ),
              ],
            );
            if (constraints.maxWidth >= 980) {
              return ResizableSplitter(
                primary: sidebar,
                secondary: transcript,
                initialPrimarySize: widget.sidebarWidth ?? 350,
                primaryMin: 280,
                secondaryMin: 420,
                onDragEnd: (value) => widget.onSidebarWidthChanged?.call(value),
              );
            }
            return Column(
              children: [
                Expanded(child: transcript),
                const SizedBox(height: 8),
                SizedBox(
                  height: math.min(260.0, constraints.maxHeight * 0.42),
                  child: sidebar,
                ),
              ],
            );
          },
        ),
      ),
    ],
  );

  // ignore: unused_element
  Widget _toolbar() => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: SectionSurface(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
      backgroundColor: Theme.of(context).colorScheme.surfaceContainerLow,
      child: Wrap(
        spacing: 8,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          FilledButton.icon(
            onPressed: widget.revision.status == 'ready'
                ? _createAtCenter
                : null,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('New block at center'),
          ),
          OutlinedButton.icon(
            onPressed: _controller.activeBlock == null
                ? null
                : () => revealEvidenceBlock(_controller.activeBlock!.id),
            icon: const Icon(Icons.center_focus_strong, size: 18),
            label: const Text('Reveal active block'),
          ),
          OutlinedButton.icon(
            onPressed: () => _run(_controller.reload),
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Reload evidence'),
          ),
          Text(
            '${widget.revision.messages} messages · '
            '${_controller.blocks.length} evidence blocks',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );

  // ignore: unused_element
  Widget _inspector() {
    final active = _controller.activeBlock;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SectionHeader(
              title: 'Evidence blocks',
              description: 'Selection and exact-range inspector.',
              leading: Icon(Icons.bookmarks_outlined, size: 19),
            ),
            const SizedBox(height: 6),
            Text(
              'The visible block nearest the center markers becomes editable. '
              'It stays active while any of its context remains visible. '
              'The eye only hides transcript markup; it does not delete or change the block.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Expanded(
              child: _controller.blocks.isEmpty
                  ? const Center(child: Text('No evidence blocks yet.'))
                  : ListView.separated(
                      itemCount: _controller.blocks.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final block = _controller.blocks[index];
                        final hidden = _controller.isHidden(block.id);
                        return ListTile(
                          dense: true,
                          selected: active?.id == block.id,
                          contentPadding: const EdgeInsets.only(left: 8),
                          title: Text(
                            block.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          subtitle: Text('${block.messageIds.length} messages'),
                          onTap: () => revealEvidenceBlock(block.id),
                          trailing: IconButton(
                            tooltip: hidden
                                ? 'Show this block’s transcript markup'
                                : 'Hide this block’s transcript markup',
                            onPressed: () =>
                                _controller.setHidden(block.id, !hidden),
                            icon: Icon(
                              hidden ? Icons.visibility_off : Icons.visibility,
                            ),
                          ),
                        );
                      },
                    ),
            ),
            const Divider(),
            if (active == null)
              const Padding(
                padding: EdgeInsets.all(8),
                child: Text(
                  'Select a block to edit its title, summary, boundaries, primary message, and highlights.',
                ),
              )
            else ...[
              TextField(
                controller: _title,
                decoration: const InputDecoration(
                  labelText: 'Title',
                  isDense: true,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _summary,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Summary',
                  alignLabelWithHint: true,
                  isDense: true,
                ),
              ),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: () => _run(
                  () => _controller.saveMetadata(_title.text, _summary.text),
                ),
                child: const Text('Save title and summary'),
              ),
              const SizedBox(height: 6),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: Theme.of(context).colorScheme.error,
                  side: BorderSide(color: Theme.of(context).colorScheme.error),
                ),
                onPressed: _deleteActiveBlock,
                icon: const Icon(Icons.delete_outline),
                label: const Text('Delete evidence block'),
              ),
              const SizedBox(height: 6),
              Text(
                'Drag the four labeled lines in the transcript. '
                'Use the circle to choose one primary message and the star '
                'to highlight messages inside the relevant section.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
