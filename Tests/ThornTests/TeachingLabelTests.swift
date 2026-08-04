import XCTest
@testable import Thorn

/// The teaching metadata tables, pinned case by case.
///
/// Two silent failure modes live here. A raw value renamed on the Swift side
/// stops matching what the sidecar sends, and `decodeIfPresent` + `flatMap`
/// turns that into `nil` rather than an error: the card quietly falls back to
/// the coarse role label and nothing reports a problem. A mistyped Chinese
/// label is even quieter — it just shows up on the card wrong.
///
/// Every row below is (case, wire string, card label), written out by hand so
/// the test disagrees with the source rather than restating it.
final class TeachingLabelTests: XCTestCase {
    private struct FunctionRow {
        let value: ChunkFunction
        let wire: String
        let label: String
        let displayRole: ChunkRole
    }

    private struct FormRow {
        let value: ChunkForm
        let wire: String
        let label: String
    }

    private static let functions: [FunctionRow] = [
        .init(value: .subject, wire: "subject", label: "主语", displayRole: .subject),
        .init(value: .predicate, wire: "predicate", label: "谓语", displayRole: .verb),
        .init(value: .object, wire: "object", label: "宾语", displayRole: .object),
        .init(value: .complement, wire: "complement", label: "补语", displayRole: .complement),
        .init(value: .adverbial, wire: "adverbial", label: "状语", displayRole: .adverbial),
        .init(value: .modifier, wire: "modifier", label: "定语", displayRole: .clauseRelative),
        .init(value: .connector, wire: "connector", label: "连接成分", displayRole: .conjunction),
        .init(value: .logicalSubject, wire: "logical-subject", label: "逻辑主语",
              displayRole: .subject),
        .init(value: .content, wire: "content", label: "引语内容", displayRole: .clauseNoun),
    ]

    private static let forms: [FormRow] = [
        .init(value: .prepositionalPhrase, wire: "prepositional-phrase", label: "介词短语"),
        .init(value: .relativeClause, wire: "relative-clause", label: "关系从句"),
        .init(value: .appositiveClause, wire: "appositive-clause", label: "同位语从句"),
        .init(value: .adverbialClause, wire: "adverbial-clause", label: "状语从句"),
        .init(value: .nominalClause, wire: "nominal-clause", label: "名词性从句"),
        .init(value: .absoluteConstruction, wire: "absolute-construction", label: "独立主格"),
        .init(value: .whInfinitive, wire: "wh-infinitive", label: "疑问词不定式"),
        .init(value: .whWord, wire: "wh-word", label: "疑问词"),
        .init(value: .infinitivePredicate, wire: "infinitive-predicate", label: "不定式"),
        .init(value: .withComplex, wire: "with-complex", label: "with 复合结构"),
        .init(value: .preposition, wire: "preposition", label: "介词"),
        .init(value: .participialClause, wire: "participial-clause", label: "分词小句"),
        .init(value: .presentParticiple, wire: "present-participle", label: "现在分词"),
        .init(value: .pastParticiple, wire: "past-participle", label: "过去分词"),
        .init(value: .reducedRelative, wire: "reduced-relative", label: "分词后置结构"),
        .init(value: .directQuotation, wire: "direct-quotation", label: "直接引语"),
    ]

    /// A case added to the enum without a row here would otherwise ship
    /// untested — this is what makes the tables above stay honest.
    func testEveryCaseIsCovered() {
        XCTAssertEqual(Set(Self.functions.map(\.value)), Set(ChunkFunction.allCases))
        XCTAssertEqual(Set(Self.forms.map(\.value)), Set(ChunkForm.allCases))
    }

    func testFunctionWireValuesAndLabels() {
        for row in Self.functions {
            XCTAssertEqual(row.value.rawValue, row.wire)
            XCTAssertEqual(ChunkFunction(rawValue: row.wire), row.value)
            XCTAssertEqual(row.value.label, row.label)
            XCTAssertEqual(row.value.displayRole, row.displayRole)
        }
    }

    func testFormWireValuesAndLabels() {
        for row in Self.forms {
            XCTAssertEqual(row.value.rawValue, row.wire)
            XCTAssertEqual(ChunkForm(rawValue: row.wire), row.value)
            XCTAssertEqual(row.value.label, row.label)
        }
    }

    /// Two cases sharing a label would put the same word on cards that mean
    /// different things — within one enum that is always a copy-paste slip.
    /// Across the two it is legitimate: 独立主格 is both a form and a role.
    func testLabelsAreDistinctWithinEachTable() {
        XCTAssertEqual(Set(ChunkFunction.allCases.map(\.label)).count,
                       ChunkFunction.allCases.count)
        XCTAssertEqual(Set(ChunkForm.allCases.map(\.label)).count,
                       ChunkForm.allCases.count)
    }

    // MARK: - What the card actually reads

    private func chunk(function: ChunkFunction?, form: ChunkForm?,
                       role: ChunkRole = .other) -> Chunk {
        Chunk(text: "x", role: role, gloss: "", function: function, form: form)
    }

    /// Both present: the badge names the job, the small label names the shape.
    func testFunctionLeadsAndFormFollows() {
        let node = chunk(function: .modifier, form: .relativeClause, role: .clauseRelative)
        XCTAssertEqual(node.primaryLabel, "定语")
        XCTAssertEqual(node.secondaryLabel, "关系从句")
        XCTAssertEqual(node.displayRole, .clauseRelative)
    }

    /// `function` overrides the parser's role for colour and text alike — this
    /// is the whole reason the field exists next to `role`.
    func testFunctionOverridesTheParserRole() {
        let node = chunk(function: .object, form: nil, role: .clauseNoun)
        XCTAssertEqual(node.primaryLabel, "宾语")
        XCTAssertNil(node.secondaryLabel)
        XCTAssertEqual(node.displayRole, .object)
    }

    /// Form alone is promoted to the badge, and must not then repeat itself in
    /// the secondary slot.
    func testFormAloneIsNotPrintedTwice() {
        let node = chunk(function: nil, form: .prepositionalPhrase, role: .prepPhrase)
        XCTAssertEqual(node.primaryLabel, "介词短语")
        XCTAssertNil(node.secondaryLabel)
        XCTAssertEqual(node.displayRole, .prepPhrase)
    }

    /// Neither present: the plain parser role, unchanged.
    func testBareChunkFallsBackToItsRole() {
        let node = chunk(function: nil, form: nil, role: .absolute)
        XCTAssertEqual(node.primaryLabel, "独立主格")
        XCTAssertNil(node.secondaryLabel)
        XCTAssertEqual(node.displayRole, .absolute)
        XCTAssertFalse(node.preservesTeachingWrapper)
    }

    /// A form of any kind marks the node as one the tree built deliberately,
    /// which keeps a single-child wrapper from being collapsed away.
    func testAnyFormPreservesTheTeachingWrapper() {
        for row in Self.forms {
            XCTAssertTrue(chunk(function: nil, form: row.value).preservesTeachingWrapper,
                          "\(row.wire) should preserve its wrapper")
        }
    }
}
