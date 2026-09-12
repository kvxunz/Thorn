import XCTest
@testable import Thorn

final class SidecarLifecycleTests: XCTestCase {
    func testStartupBudgetIncludesProbeTime() {
        let start = ContinuousClock.now
        let budget = SidecarStartupBudget(start: start)

        XCTAssertEqual(budget.remaining(at: start), 60, accuracy: 0.001)
        XCTAssertEqual(budget.probeTimeout(at: start), 2, accuracy: 0.001)
        XCTAssertEqual(budget.probeTimeout(at: start.advanced(by: .seconds(59))), 1, accuracy: 0.001)
        XCTAssertEqual(budget.remaining(at: start.advanced(by: .seconds(60))), 0)
        XCTAssertEqual(budget.probeTimeout(at: start.advanced(by: .seconds(61))), 0)
    }

    func testStartupSleepCannotExtendPastDeadline() {
        let start = ContinuousClock.now
        let budget = SidecarStartupBudget(start: start)

        XCTAssertEqual(budget.nextPoll(at: start), start.advanced(by: .milliseconds(500)))
        XCTAssertEqual(budget.nextPoll(at: start.advanced(by: .milliseconds(59_900))), budget.deadline)
    }

    func testProcessLaunchUsesScriptDirectoryInsteadOfFinderRoot() {
        let process = Process()

        Sidecar.configureProcess(
            process,
            script: "/Applications/Thorn.app/Contents/Resources/sidecar/server.py",
            port: 54_321,
            idleExitSeconds: 300,
            authToken: "test-token",
            environment: ["PATH": "/usr/bin:/bin"]
        )

        XCTAssertEqual(
            process.currentDirectoryURL?.path,
            "/Applications/Thorn.app/Contents/Resources/sidecar"
        )
        XCTAssertEqual(process.environment?["THORN_SIDECAR_TOKEN"], "test-token")
        XCTAssertEqual(process.environment?["PATH"], "/usr/bin:/bin")
    }

    func testFailedLaunchReturnsToIdleForRetry() {
        var state = SidecarLifecycleState()

        XCTAssertTrue(state.beginLaunch())
        XCTAssertEqual(state.phase, .launching)
        state.launchFailed()

        XCTAssertEqual(state.phase, .idle)
        XCTAssertTrue(state.beginLaunch())
    }

    func testExitedProcessCanBeRespawned() {
        var state = SidecarLifecycleState()

        XCTAssertTrue(state.beginLaunch())
        XCTAssertTrue(state.launchSucceeded())
        let firstGeneration = state.generation
        XCTAssertEqual(state.phase, .running)
        state.processExited()

        XCTAssertEqual(state.phase, .idle)
        XCTAssertTrue(state.beginLaunch())
        XCTAssertTrue(state.launchSucceeded())
        XCTAssertGreaterThan(state.generation, firstGeneration)
    }

    func testOnlyOneLaunchCanBeInFlight() {
        var state = SidecarLifecycleState()

        XCTAssertTrue(state.beginLaunch())
        XCTAssertFalse(state.beginLaunch())
        XCTAssertTrue(state.launchSucceeded())
        XCTAssertFalse(state.beginLaunch())
    }

    func testStaleHealthResponseCannotMarkReplacementReady() {
        var state = SidecarLifecycleState()
        XCTAssertTrue(state.beginLaunch())
        XCTAssertTrue(state.launchSucceeded())
        let staleGeneration = state.generation

        state.processExited()
        XCTAssertTrue(state.beginLaunch())
        XCTAssertTrue(state.launchSucceeded())

        XCTAssertFalse(
            state.acceptsHealthResponse(
                generation: staleGeneration,
                processIsRunning: true
            )
        )
        XCTAssertTrue(
            state.acceptsHealthResponse(
                generation: state.generation,
                processIsRunning: true
            )
        )
        XCTAssertFalse(
            state.acceptsHealthResponse(
                generation: state.generation,
                processIsRunning: false
            )
        )
    }

    func testShutdownRejectsLateProcessRegistration() {
        var state = SidecarShutdownState()
        XCTAssertTrue(state.allowsProcessRegistration)

        state.beginShutdown()

        XCTAssertTrue(state.isShuttingDown)
        XCTAssertFalse(state.allowsProcessRegistration)
    }
}
