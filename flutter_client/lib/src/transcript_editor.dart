import 'dart:collection';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'evw_database.dart';
import 'evw_models.dart';
import 'transcript_height_index.dart';

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

  int get evidenceDataVersion => _evidenceDataVersion;

  List<EvidenceBlock> get blocks => List.unmodifiable(_blocks);
  int? get activeBlockId => _activeBlockId;
  EvidenceBlock? get activeBlock => _blockById(_activeBlockId);

  void reload() {
    _blocks = database.evidenceBlocks(revision.id);
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
    String createdBy = 'transcript_editor',
  }) {
    final block = database.createEvidenceBlock(
      revisionId: revision.id,
      hitOrdinal: ordinal,
      createdBy: createdBy,
    );
    _replaceBlock(block);
    _activeBlockId = block.id;
    _hiddenBlockIds.remove(block.id);
    _notify(persisted: true);
    return block;
  }

  void saveMetadata(String title, String summary) {
    final block = activeBlock;
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

  void deleteActiveBlock() {
    final block = activeBlock;
    if (block == null) throw StateError('Select an evidence block first');
    database.deleteEvidenceBlock(
      revisionId: revision.id,
      evidenceBlockId: block.id,
    );
    _hiddenBlockIds.remove(block.id);
    _activeBlockId = null;
    _blocks.removeWhere((item) => item.id == block.id);
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
    final bodyWidth = math.max(180.0, width - 190);
    final sender = TextPainter(
      text: TextSpan(
        text: message.sender,
        style: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          height: 1.2,
        ),
      ),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: bodyWidth);
    final body = TextPainter(
      text: TextSpan(
        text: message.body,
        style: const TextStyle(fontSize: 14, height: 1.35),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: bodyWidth);
    return math.max(76, 18 + sender.height + 6 + body.height + 32);
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

    final messages = <TranscriptMessage>[];
    for (var ordinal = start; ordinal < end; ordinal++) {
      final message = _messageAt(ordinal);
      if (message != null) messages.add(message);
    }
    for (final message in messages) {
      _heightIndex.setHeight(message.ordinal, _measureMessage(message, width));
    }
    return messages.map((message) {
      final annotation = widget.controller.annotationFor(message);
      return Positioned(
        top: _heightIndex.offsetForOrdinal(message.ordinal),
        left: 24,
        right: 24,
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
      _scheduleViewportActivation();
      return DecoratedBox(
        decoration: const BoxDecoration(color: Color(0xfff3f1ed)),
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
                child: Container(
                  height: 1,
                  margin: const EdgeInsets.only(left: 8, right: 22),
                  decoration: const BoxDecoration(
                    border: Border(
                      top: BorderSide(
                        color: Color(0x55707070),
                        style: BorderStyle.solid,
                      ),
                    ),
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
        ? const Color(0xfffff2a8)
        : annotation.relevant
        ? const Color(0xffe2f1dc)
        : annotation.context
        ? const Color(0xffe9e6e0)
        : Colors.white;
    final subdued = annotation.context && !annotation.relevant;
    return ColoredBox(
      color: background,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 10, 10),
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
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: subdued
                                ? const Color(0xff666666)
                                : const Color(0xff151515),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        message.timestamp,
                        style: const TextStyle(
                          fontSize: 11,
                          color: Color(0xff777777),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 5),
                  SelectableText(
                    message.body,
                    style: TextStyle(
                      fontSize: 14,
                      height: 1.35,
                      fontWeight: annotation.relevant || annotation.highlighted
                          ? FontWeight.w500
                          : FontWeight.normal,
                      color: subdued
                          ? const Color(0xff666666)
                          : const Color(0xff151515),
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${message.threadTitle} · message ${message.ordinal + 1}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 10,
                      color: Color(0xff888888),
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
                          color: annotation.primary
                              ? const Color(0xff245b9e)
                              : null,
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
                              ? const Color(0xff9b7200)
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
              color: Colors.white,
              border: Border.all(color: const Color(0xff245b9e)),
              borderRadius: BorderRadius.circular(3),
            ),
            child: Text(
              boundary.label,
              style: const TextStyle(
                fontSize: 11,
                color: Color(0xff245b9e),
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 6),
          const Expanded(
            child: Divider(color: Color(0xff245b9e), thickness: 2, height: 2),
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
  });

  final EvwDatabase database;
  final RevisionSummary revision;
  final TranscriptDocumentController? controller;
  final bool isPageActive;

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
    final block = _controller.activeBlock;
    if (block?.id == _metadataBlockId) return;
    _metadataBlockId = block?.id;
    _title.text = block?.title ?? '';
    _summary.text = block?.summary ?? '';
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
      final block = _controller.createAtOrdinal(ordinal);
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
      result = _controller.createAtOrdinal(ordinal, createdBy: createdBy);
      _transcriptKey.currentState?.scrollToOrdinal(ordinal);
    });
    return result;
  }

  Future<void> _deleteActiveBlock() async {
    final block = _controller.activeBlock;
    if (block == null) return;
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
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete block'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      _run(_controller.deleteActiveBlock);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      _toolbar(),
      if (_error != null)
        MaterialBanner(
          content: SelectableText('FAILED\n$_error'),
          actions: [
            TextButton(
              onPressed: () => setState(() => _error = null),
              child: const Text('Dismiss'),
            ),
          ],
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
            final inspector = _inspector();
            if (constraints.maxWidth >= 980) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(child: transcript),
                  const SizedBox(width: 12),
                  SizedBox(width: 350, child: inspector),
                ],
              );
            }
            return Column(
              children: [
                Expanded(child: transcript),
                const SizedBox(height: 8),
                SizedBox(
                  height: math.min(260.0, constraints.maxHeight * 0.42),
                  child: inspector,
                ),
              ],
            );
          },
        ),
      ),
    ],
  );

  Widget _toolbar() => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Wrap(
      spacing: 8,
      runSpacing: 6,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        FilledButton.icon(
          onPressed: widget.revision.status == 'ready' ? _createAtCenter : null,
          icon: const Icon(Icons.add),
          label: const Text('New block at center'),
        ),
        OutlinedButton.icon(
          onPressed: _controller.activeBlock == null
              ? null
              : () => revealEvidenceBlock(_controller.activeBlock!.id),
          icon: const Icon(Icons.center_focus_strong),
          label: const Text('Reveal active block'),
        ),
        OutlinedButton.icon(
          onPressed: () => _run(_controller.reload),
          icon: const Icon(Icons.refresh),
          label: const Text('Reload evidence'),
        ),
        Text(
          '${widget.revision.messages} messages · '
          '${_controller.blocks.length} evidence blocks',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    ),
  );

  Widget _inspector() {
    final active = _controller.activeBlock;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Evidence blocks',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              'The visible block nearest the center line becomes editable. '
              'It stays active while any of its context remains visible. '
              'The eye only hides transcript markup; it does not delete or change the block.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 6),
            Expanded(
              child: _controller.blocks.isEmpty
                  ? const Center(child: Text('No evidence blocks yet.'))
                  : ListView.builder(
                      itemCount: _controller.blocks.length,
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
