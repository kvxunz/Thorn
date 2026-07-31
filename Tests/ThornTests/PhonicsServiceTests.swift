import XCTest
@testable import Thorn

final class PhonicsServiceTests: XCTestCase {

    // MARK: - Single-word detection

    func testSingleWordDetection() {
        XCTAssertEqual(ParseService.singleWord(in: "serendipity"), "serendipity")
        XCTAssertEqual(ParseService.singleWord(in: "  Thorn,  "), "Thorn")
        XCTAssertEqual(ParseService.singleWord(in: "“vocabulary”"), "vocabulary")
        XCTAssertEqual(ParseService.singleWord(in: "don't"), "don't")
        XCTAssertEqual(ParseService.singleWord(in: "don’t."), "don't")
        XCTAssertEqual(ParseService.singleWord(in: "mother-in-law"), "mother-in-law")
        XCTAssertEqual(ParseService.singleWord(in: "(ubiquitous)"), "ubiquitous")
        XCTAssertEqual(ParseService.singleWord(in: "dogs'"), "dogs")
        XCTAssertEqual(ParseService.singleWord(in: "I"), "I")
    }

    func testSentenceLikeInputIsNotAWord() {
        XCTAssertNil(ParseService.singleWord(in: "two words"))
        XCTAssertNil(ParseService.singleWord(in: "The cat sat."))
        XCTAssertNil(ParseService.singleWord(in: "word1"))
        XCTAssertNil(ParseService.singleWord(in: "3.14"))
        XCTAssertNil(ParseService.singleWord(in: ""))
        XCTAssertNil(ParseService.singleWord(in: "..."))
        XCTAssertNil(ParseService.singleWord(in: "e.g"))
    }

    // MARK: - Binary search over a sorted TSV buffer

    private let buffer = Data([
        "apple\tˈæpəl\tˈ[a:æ].[pp:p|le:əl]",
        "banana\tbəˈnænə\t[b:b|a:ə].ˈ[n:n|a:æ].[n:n|a:ə]",
        "cherry\tˈtʃeriː\tˈ[ch:tʃ|e:e].[rr:r|y:iː]",
        "date\tˈdeɪt\tˈ[d:d|a:eɪ|te:t]",
        "",
    ].joined(separator: "\n").utf8)

    func testLookupFindsFirstMiddleAndLastEntries() {
        XCTAssertTrue(PhonicsService.lookupLine("apple", in: buffer)?.hasPrefix("apple\t") ?? false)
        XCTAssertTrue(PhonicsService.lookupLine("banana", in: buffer)?.hasPrefix("banana\t") ?? false)
        XCTAssertTrue(PhonicsService.lookupLine("date", in: buffer)?.hasPrefix("date\t") ?? false)
    }

    func testLookupMissesAbsentAndPrefixWords() {
        XCTAssertNil(PhonicsService.lookupLine("cedar", in: buffer))
        XCTAssertNil(PhonicsService.lookupLine("app", in: buffer))     // prefix of a key
        XCTAssertNil(PhonicsService.lookupLine("appleseed", in: buffer)) // key is its prefix
        XCTAssertNil(PhonicsService.lookupLine("zebra", in: buffer))
        XCTAssertNil(PhonicsService.lookupLine("", in: buffer))
    }

    // MARK: - TSV entry parsing

    func testParseEntryRoundTrip() throws {
        let line = "about\təˈbaʊt\t[a:ə].ˈ[b:b|ou:aʊ|t:t]"
        let entry = try XCTUnwrap(PhonicsService.parseEntry(line: line))
        XCTAssertEqual(entry.word, "about")
        XCTAssertEqual(entry.ipa, "əˈbaʊt")
        XCTAssertFalse(entry.approximate)
        XCTAssertEqual(entry.syllables.count, 2)
        XCTAssertEqual(entry.syllables[0].stress, .none)
        XCTAssertEqual(entry.syllables[1].stress, .primary)
        XCTAssertEqual(entry.syllables[1].chunks.map(\.grapheme), ["b", "ou", "t"])
        XCTAssertEqual(entry.syllables[1].chunks.map(\.ipa), ["b", "aʊ", "t"])
    }

    func testParseEntryRejectsGraphemeMismatch() {
        // Chunks rebuild "abut", not "about" — integrity check must refuse.
        XCTAssertNil(PhonicsService.parseEntry(line: "about\təˈbaʊt\t[a:ə].ˈ[b:b|u:aʊ|t:t]"))
    }

    func testParseEntryRejectsMalformedLines() {
        XCTAssertNil(PhonicsService.parseEntry(line: "about\təˈbaʊt")) // missing field
        XCTAssertNil(PhonicsService.parseEntry(line: "about\t\t[a:ə]")) // empty ipa
        XCTAssertNil(PhonicsService.parseEntry(line: "about\tx\ta:ə"))  // no brackets
    }

    // MARK: - Heuristic fallback

    func testHeuristicSplitKeepsDigraphsTogether() {
        let result = PhonicsService.heuristicSplit(word: "sheeple")
        XCTAssertTrue(result.approximate)
        XCTAssertNil(result.ipa)
        let graphemes = result.syllables.flatMap(\.chunks).map(\.grapheme)
        XCTAssertEqual(graphemes.joined(), "sheeple")
        XCTAssertTrue(graphemes.contains("sh"))
        XCTAssertTrue(graphemes.contains("ee"))
    }

    func testHeuristicSplitMagicE() {
        let graphemes = PhonicsService.heuristicSplit(word: "frobmake")
            .syllables.flatMap(\.chunks).map(\.grapheme)
        XCTAssertEqual(graphemes.joined(), "frobmake")
        XCTAssertEqual(graphemes.last, "ke") // trailing silent e joins its consonant
    }

    func testHeuristicSplitRebuildsAnyWord() {
        for word in ["zyzzyva", "blorptastic", "qwerty", "grok'd", "e", "tsktsk"] {
            let result = PhonicsService.heuristicSplit(word: word)
            XCTAssertEqual(
                result.syllables.flatMap(\.chunks).map(\.grapheme).joined(),
                word,
                "graphemes must rebuild \(word)"
            )
            XCTAssertFalse(result.syllables.isEmpty)
        }
    }

    func testHeuristicSplitIsDeterministic() {
        let first = PhonicsService.heuristicSplit(word: "blorptastic")
        let second = PhonicsService.heuristicSplit(word: "blorptastic")
        XCTAssertEqual(first, second)
    }

    // MARK: - Real bundled dictionary (skipped when not generated)

    func testRealDictionaryLookup() throws {
        guard PhonicsService.lookupLine("about") != nil else {
            throw XCTSkip("phonics-en.tsv not available on this machine")
        }
        let result = PhonicsService.decompose(word: "About")
        XCTAssertFalse(result.approximate)
        XCTAssertEqual(result.word, "about")
        XCTAssertEqual(
            result.syllables.flatMap(\.chunks).map(\.grapheme).joined(),
            "about"
        )
        XCTAssertNotNil(result.ipa)
        XCTAssertTrue(result.syllables.contains { $0.stress == .primary })
    }

    func testDecomposeFallsBackForUnknownWords() {
        let result = PhonicsService.decompose(word: "blorptastic")
        XCTAssertTrue(result.approximate)
    }
}
