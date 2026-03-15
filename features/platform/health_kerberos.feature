@platform @health @kerberos
Feature: Kerberos KDC health

  @tier-0
  Scenario: kinit obtains a valid TGT
    When I run kinit for "signals@KRBTEST.COM" with password "signals"
    Then kinit succeeds
    And klist shows a TGT for "signals@KRBTEST.COM"

  @tier-0
  Scenario: Postgres service keytab is valid
    Then the keytab at ".devenv/kdc/postgres.keytab" exists
    And ktutil shows principal "postgres/localhost@KRBTEST.COM" in the keytab

  @tier-0
  Scenario: KDC has correct realm configuration
    When I run kadmin.local to list principals
    Then the output contains "signals@KRBTEST.COM"
    And the output contains "postgres/localhost@KRBTEST.COM"
