Feature: Twister results

  @TWS-01 @TWS-02
  Scenario: All tests pass
    Given a test suite with 4 passing cases
    When the agent calls "twister" for that suite on "native_sim"
    Then the result shows 1 suite passed and 0 failed

  @TWS-03
  Scenario: Failing test case
    Given a suite where case "test_parse_empty" fails an assertion
    When the agent calls "twister" for that suite
    Then the result lists failed case "test_parse_empty"
    And its log excerpt contains the assertion message
    And the excerpt has at most 40 lines

  @TWS-04
  Scenario: Test fails to build
    Given a suite that does not compile
    When the agent calls "twister" for that suite
    Then the result contains a build diagnostic with category "compiler"

  @TWS-05
  Scenario: Report output locations
    When the agent calls "twister" for a suite
    Then the result contains the path to Twister's output directory
    And the result contains the path to its JSON report, and that file exists

  @TWS-06
  Scenario: Hardware test with capture open
    Given a serial capture is open on the board
    When the agent calls "twister" with device testing
    Then zquire releases the port during the run
    And capture resumes after the run

  @TWS-07
  Scenario: Run exceeds timeout
    Given a suite that hangs
    When the agent calls "twister" with timeout 60 s
    Then the status is "timeout" after about 60 s
