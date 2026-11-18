Feature: ZView filtered stats

  @ZV-10
  Scenario: Threads only
    Given the prerequisites are met
    When the agent calls "runtime_stats" with include "threads"
    Then the result contains threads
    And the result contains no heaps

  @ZV-11
  Scenario: One specific thread
    Given threads "main", "sensor" and "idle" exist
    When the agent calls "runtime_stats" with threads ["sensor"]
    Then exactly one thread "sensor" is returned

  @ZV-12
  Scenario: Some names missing
    Given threads "main" and "sensor" exist
    When the agent calls "runtime_stats" with threads ["sensor", "radio"]
    Then thread "sensor" is returned
    And not_found lists "radio"

  @ZV-12
  Scenario: All names missing
    When the agent calls "runtime_stats" with heaps ["no_such_heap"]
    Then the call fails with error "NOT_FOUND"
