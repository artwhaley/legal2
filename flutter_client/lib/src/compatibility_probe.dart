import 'evw_database.dart';

void runCompatibilityProbe(String path) {
  final db = EvwDatabase.open(path);
  try {
    final corpora = db.corpora();
    final revisions = db.revisions();
    final readyRevisions = revisions
        .where((revision) => revision.status == 'ready')
        .toList();
    final messages = readyRevisions.isEmpty
        ? <Object>[]
        : db.transcript(readyRevisions.first.id, limit: 10);
    final allEvidence = db.evidence(null);
    var scopedEvidenceReads = 0;
    for (final revision in revisions) {
      db.evidence(revision.id);
      scopedEvidenceReads += 1;
    }
    print('EVW v15 probe: PASS');
    print(
      'path=${db.path} corpora=${corpora.length} revisions=${revisions.length} sample_messages=${messages.length} evidence=${allEvidence.length} scoped_evidence_reads=$scopedEvidenceReads',
    );
  } finally {
    db.close();
  }
}
