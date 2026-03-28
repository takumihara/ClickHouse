-- Tags: no-fasttest

-- Verify that isIPAddressInRange returns 0 for invalid IP addresses
-- instead of throwing an exception.
-- GitHub issue: https://github.com/ClickHouse/ClickHouse/issues/65911

-- Empty string
SELECT isIPAddressInRange('', '192.168.0.0/16');
SELECT isIPAddressInRange('', '::ffff:192.168.0.0/112');

-- Invalid IP address strings
SELECT isIPAddressInRange('not_an_ip', '192.168.0.0/16');
SELECT isIPAddressInRange('abc', '10.0.0.0/8');

-- Valid cases still work
SELECT isIPAddressInRange('192.168.1.1', '192.168.0.0/16');
SELECT isIPAddressInRange('10.0.0.1', '192.168.0.0/16');
SELECT isIPAddressInRange('::ffff:192.168.1.1', '::ffff:192.168.0.0/112');

-- Consistency with isIPv4String / isIPv6String
SELECT isIPv4String('');
SELECT isIPv6String('');
