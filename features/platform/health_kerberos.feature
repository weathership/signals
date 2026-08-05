@platform @health @kerberos
Feature: Kerberos KDC health

  @tier-0
  Scenario: kinit obtains a valid TGT
    When I run kinit for "signals@DEV.VISTA.ZNDX.ORG" with password "signals"
    Then kinit succeeds
    And klist shows a TGT for "signals@DEV.VISTA.ZNDX.ORG"

  @tier-0
  Scenario: Postgres service keytab is valid
    Then the keytab at ".devenv/kdc/postgres.keytab" exists
    And ktutil shows principal "postgres/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG" in the keytab

  @tier-0
  Scenario: KDC has correct realm configuration
    When I run kadmin.local to list principals
    Then the output contains "signals@DEV.VISTA.ZNDX.ORG"
    And the output contains "postgres/tinybox.dev.vista.zndx.org@DEV.VISTA.ZNDX.ORG"
