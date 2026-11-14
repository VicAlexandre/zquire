Feature: Build with structured diagnostics

  @BLD-01 @BLD-02 @BLD-06 @BLD-10
  Scenario: Successful build
    Given an application that compiles cleanly for the active board
    When the agent calls "build"
    Then the status is "success"
    And the result contains flash and RAM usage per region
    And the active profile records this as its latest successful build

  @BLD-03 @BLD-04
  Scenario: Compiler error
    Given "src/main.c" line 42 calls an undeclared function "foo"
    When the agent calls "build"
    Then the status is "failure"
    And there is a diagnostic with category "compiler" and severity "error"
    And that diagnostic points to "src/main.c" line 42

  @BLD-03 @BLD-04
  Scenario: Kconfig misconfiguration
    Given prj.conf sets a symbol whose dependencies are not met
    When the agent calls "build"
    Then there is a diagnostic with category "kconfig"
    And its message names the symbol and its unmet dependency

  @BLD-03 @BLD-04
  Scenario: Devicetree error
    Given an overlay references a node label that does not exist
    When the agent calls "build"
    Then there is a diagnostic with category "devicetree"
    And it points to the overlay file and line

  @BLD-05 @BLD-09
  Scenario: Unrecognised failure
    Given a build fails with output zquire cannot parse
    When the agent calls "build"
    Then there is exactly one diagnostic with category "unknown"
    And it includes a log excerpt of at most 60 lines
    And the result contains the path to the full build log

  @BLD-07
  Scenario: RAM overflow
    Given an application whose static RAM exceeds the board's RAM by 2048 bytes
    When the agent calls "build"
    Then there is a diagnostic with category "memory_overflow"
    And it names region "RAM" and overflow 2048 bytes

  @BLD-08
  Scenario: Repeated warning
    Given a header produces the same warning in 12 source files
    When the agent calls "build"
    Then that warning appears once with repeat count 12
