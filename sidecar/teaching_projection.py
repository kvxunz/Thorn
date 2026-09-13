from alignment import annotate_chunk_spans
from grammar_notes import annotate_grammar_notes
from syntax_assembly import analyze_structure
from teaching_policy import TeachingPolicy
from teaching_tree import compile_teaching_tree


def project_structure(structure, doc, source, evidence, *, policy=None):
    teaching_chunks = compile_teaching_tree(source, structure.payload(), evidence=evidence)
    chunks = annotate_chunk_spans(source.text, teaching_chunks, source.token_offsets)
    annotate_grammar_notes(chunks, doc)
    return (policy or TeachingPolicy()).project(chunks)


def project_document(doc, source, evidence, *, trace=False, policy=None):
    structure = analyze_structure(doc, evidence.relations, trace=trace)
    chunks = project_structure(structure, doc, source, evidence, policy=policy)
    return chunks, structure.decisions()
