class CorpusSummary {
  const CorpusSummary(this.id, this.name, this.currentRevisionId);
  final int id;
  final String name;
  final int? currentRevisionId;
}

class RevisionSummary {
  const RevisionSummary({
    required this.id,
    required this.corpusId,
    required this.datasetId,
    required this.number,
    required this.status,
    required this.messages,
    required this.tokens,
    required this.scopeHash,
    required this.generation,
    this.ftsStatus,
    required this.messageEmbeddingStatus,
    required this.chunkEmbeddingStatus,
  });
  final int id;
  final int corpusId;
  final int datasetId;
  final int number;
  final String status;
  final int messages;
  final int tokens;
  final String scopeHash;
  final int? generation;
  final String? ftsStatus;
  final String? messageEmbeddingStatus;
  final String? chunkEmbeddingStatus;
}

class TranscriptMessage {
  const TranscriptMessage({
    required this.id,
    required this.threadId,
    required this.threadTitle,
    required this.ordinal,
    required this.timestamp,
    required this.sender,
    required this.body,
  });
  final String id;
  final String threadId;
  final String threadTitle;
  final int ordinal;
  final String timestamp;
  final String sender;
  final String body;
}

class EvidenceBlock {
  const EvidenceBlock({
    required this.id,
    required this.datasetId,
    required this.categoryId,
    required this.sourceThreadId,
    required this.title,
    required this.summary,
    required this.contextStartMessageId,
    required this.relevantStartMessageId,
    required this.coreMessageId,
    required this.relevantEndMessageId,
    required this.contextEndMessageId,
    required this.contextStartOrdinal,
    required this.relevantStartOrdinal,
    required this.coreOrdinal,
    required this.relevantEndOrdinal,
    required this.contextEndOrdinal,
    required this.messageIds,
    required this.sections,
    required this.highlightedMessageIds,
  });

  final int id;
  final int datasetId;
  final int categoryId;
  final String sourceThreadId;
  final String title;
  final String summary;
  final String contextStartMessageId;
  final String relevantStartMessageId;
  final String coreMessageId;
  final String relevantEndMessageId;
  final String contextEndMessageId;
  final int contextStartOrdinal;
  final int relevantStartOrdinal;
  final int coreOrdinal;
  final int relevantEndOrdinal;
  final int contextEndOrdinal;
  final List<String> messageIds;
  final Map<String, String> sections;
  final Set<String> highlightedMessageIds;

  bool contains(TranscriptMessage message) =>
      message.threadId == sourceThreadId &&
      message.ordinal >= contextStartOrdinal &&
      message.ordinal <= contextEndOrdinal;

  bool isRelevant(TranscriptMessage message) =>
      contains(message) &&
      message.ordinal >= relevantStartOrdinal &&
      message.ordinal <= relevantEndOrdinal;

  EvidenceBlock copyWith({
    String? title,
    String? summary,
    String? contextStartMessageId,
    String? relevantStartMessageId,
    String? coreMessageId,
    String? relevantEndMessageId,
    String? contextEndMessageId,
    int? contextStartOrdinal,
    int? relevantStartOrdinal,
    int? coreOrdinal,
    int? relevantEndOrdinal,
    int? contextEndOrdinal,
    List<String>? messageIds,
    Map<String, String>? sections,
    Set<String>? highlightedMessageIds,
  }) => EvidenceBlock(
    id: id,
    datasetId: datasetId,
    categoryId: categoryId,
    sourceThreadId: sourceThreadId,
    title: title ?? this.title,
    summary: summary ?? this.summary,
    contextStartMessageId: contextStartMessageId ?? this.contextStartMessageId,
    relevantStartMessageId:
        relevantStartMessageId ?? this.relevantStartMessageId,
    coreMessageId: coreMessageId ?? this.coreMessageId,
    relevantEndMessageId: relevantEndMessageId ?? this.relevantEndMessageId,
    contextEndMessageId: contextEndMessageId ?? this.contextEndMessageId,
    contextStartOrdinal: contextStartOrdinal ?? this.contextStartOrdinal,
    relevantStartOrdinal: relevantStartOrdinal ?? this.relevantStartOrdinal,
    coreOrdinal: coreOrdinal ?? this.coreOrdinal,
    relevantEndOrdinal: relevantEndOrdinal ?? this.relevantEndOrdinal,
    contextEndOrdinal: contextEndOrdinal ?? this.contextEndOrdinal,
    messageIds: messageIds ?? this.messageIds,
    sections: sections ?? this.sections,
    highlightedMessageIds: highlightedMessageIds ?? this.highlightedMessageIds,
  );
}

class CategorySummary {
  const CategorySummary(
    this.id,
    this.name, {
    this.isCollapsed = false,
    this.evidenceCount = 0,
  });
  final int id;
  final String name;
  final bool isCollapsed;
  final int evidenceCount;
}

class EvidenceSummary {
  const EvidenceSummary({
    required this.id,
    required this.title,
    required this.summary,
    required this.originKind,
    required this.originWorkingCorpusRevisionId,
    required this.originScopeHash,
    required this.inheritedFromRevisionId,
    required this.messageCount,
  });
  final int id;
  final String title;
  final String summary;
  final String originKind;
  final int? originWorkingCorpusRevisionId;
  final String? originScopeHash;
  final int? inheritedFromRevisionId;
  final int messageCount;
}

class SearchHit {
  const SearchHit({
    required this.messageId,
    required this.threadId,
    required this.threadTitle,
    required this.ordinal,
    required this.timestamp,
    required this.sender,
    required this.body,
    required this.matchType,
    required this.rank,
    this.distance,
  });

  final String messageId;
  final String threadId;
  final String threadTitle;
  final int ordinal;
  final String timestamp;
  final String sender;
  final String body;
  final String matchType;
  final double rank;
  final double? distance;
}

class SearchPage {
  const SearchPage({
    required this.hits,
    required this.totalCount,
    required this.hasMore,
    required this.nextOffset,
    this.invalidQueryReason,
  });

  final List<SearchHit> hits;
  final int totalCount;
  final bool hasMore;
  final int? nextOffset;
  final String? invalidQueryReason;
}

class EmbeddingGeometry {
  const EmbeddingGeometry({
    required this.dimensions,
    required this.normalization,
  });

  final int dimensions;
  final String normalization;
}

class PrintableArtifactGroupSummary {
  const PrintableArtifactGroupSummary({
    required this.id,
    required this.datasetId,
    required this.name,
    required this.sortOrder,
  });

  final int id;
  final int datasetId;
  final String name;
  final int sortOrder;
}

class PrintableArtifactSummary {
  const PrintableArtifactSummary({
    required this.id,
    required this.datasetId,
    required this.groupId,
    required this.title,
    required this.exhibitNumber,
    required this.caseNumber,
    required this.sortOrder,
  });

  final int id;
  final int datasetId;
  final int groupId;
  final String title;
  final String exhibitNumber;
  final String caseNumber;
  final int sortOrder;
}

class PrintableArtifactBlock {
  const PrintableArtifactBlock({
    required this.joinId,
    required this.artifactId,
    required this.sortOrder,
    required this.label,
    required this.evidence,
    required this.messages,
  });

  final int joinId;
  final int artifactId;
  final int sortOrder;
  final String label;
  final EvidenceBlock evidence;
  final List<TranscriptMessage> messages;
}

class PrintableArtifactDocument {
  const PrintableArtifactDocument({
    required this.artifact,
    required this.groupName,
    required this.blocks,
  });

  final PrintableArtifactSummary artifact;
  final String groupName;
  final List<PrintableArtifactBlock> blocks;
}
