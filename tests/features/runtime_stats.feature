Feature: ZView runtime stats

  @ZV-01 @ZV-02 @ZV-04
  Scenario: Thread near stack overflow
    Given a running board whose thread "sensor" uses 90 % of its stack
    And the active build has all ZView prerequisites
    When the agent calls "runtime_stats"
    Then thread "sensor" has watermark 90 %
    And thread "sensor" is flagged "stack_risk"

  @ZV-03
  Scenario: Heap usage
    Given the prerequisites are met
    And a heap "app_heap" of 4096 bytes with 1024 bytes in use
    When the agent calls "runtime_stats"
    Then heap "app_heap" has size 4096, used 1024 and free 3072

  @ZV-05 @ZV-06
  Scenario: Missing prerequisites
    Given the active .config does not set CONFIG_THREAD_MONITOR
    When the agent calls "runtime_stats"
    Then the call fails with error "ZVIEW_PREREQ"
    And the error lists "CONFIG_THREAD_MONITOR=y"
    And ZView is not invoked

  @ZV-07
  Scenario: No CPU stats available
    Given the prerequisites are met but CONFIG_THREAD_RUNTIME_STATS is not set
    When the agent calls "runtime_stats"
    Then threads are returned without CPU percent
    And the result warns to enable "CONFIG_THREAD_RUNTIME_STATS"

  @ZV-08
  Scenario: ZView not installed
    Given the workspace manifest has no zview project
    When the agent calls "runtime_stats"
    Then the call fails with error "ZVIEW_MISSING"
    And the error includes a west.yml snippet for zview

  @ZV-09
  Scenario: Runner derived from the board, with override
    Given the board's default runner is "jlink"
    When the agent calls "runtime_stats"
    Then ZView is invoked with runner "jlink"
    When the agent calls "runtime_stats" with runner "pyocd"
    Then ZView is invoked with runner "pyocd"

  @FLS-07
  Scenario: Flash during a dump
    Given a ZView dump is in progress
    When the agent calls "flash"
    Then the flash waits until the dump finishes, or fails with "BUSY" after 30 s
