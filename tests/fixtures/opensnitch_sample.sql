-- A synthetic OpenSnitch GUI database, schema DB_VERSION 3, for the collector
-- tests. Every value is a documentation value: addresses from 192.0.2.0/24,
-- 198.51.100.0/24, 203.0.113.0/24 and 2001:db8::/32, names under example.com
-- and example.net, invented process paths and accounts. Nothing here describes
-- a real machine.
--
-- The sample connections are dated 2026-10-01, a month before any window the
-- tests collect, so they always fall outside it. The lifetime counters in
-- hosts, procs, addrs, ports and users are deliberately huge: the collector
-- must never read those tables, and a test proves no aggregate carries them.

CREATE TABLE connections (
    time TEXT, node TEXT, action TEXT, protocol TEXT, src_ip TEXT,
    src_port TEXT, dst_ip TEXT, dst_host TEXT, dst_port TEXT, uid TEXT,
    pid TEXT, process TEXT, process_args TEXT, process_cwd TEXT, rule TEXT
);

CREATE TABLE nodes (
    addr TEXT, hostname TEXT, daemon_version TEXT, daemon_uptime TEXT,
    daemon_rules TEXT, cons TEXT, cons_dropped TEXT, version TEXT,
    status TEXT, last_connection TEXT
);

CREATE TABLE rules (
    time TEXT, node TEXT, name TEXT, enabled TEXT, precedence TEXT,
    action TEXT, duration TEXT, operator_type TEXT, operator_sensitive TEXT,
    operator_operand TEXT, operator_data TEXT, description TEXT, nolog TEXT,
    created TEXT
);

CREATE TABLE sockets (
    id TEXT, last_seen TEXT, node TEXT, src_port TEXT, src_ip TEXT,
    dst_ip TEXT, dst_port TEXT, proto TEXT, uid TEXT, inode TEXT,
    iface TEXT, family TEXT, state TEXT, cookies TEXT, rqueue TEXT,
    wqueue TEXT, expires TEXT, retrans TEXT, timer TEXT, mark TEXT,
    proc_pid TEXT, proc_comm TEXT, proc_path TEXT
);

CREATE TABLE alerts (
    time TEXT, node TEXT, type TEXT, action TEXT, priority TEXT, what TEXT,
    body TEXT, status TEXT
);

CREATE TABLE hosts (what TEXT PRIMARY KEY, hits INTEGER);
CREATE TABLE procs (what TEXT PRIMARY KEY, hits INTEGER);
CREATE TABLE addrs (what TEXT PRIMARY KEY, hits INTEGER);
CREATE TABLE ports (what TEXT PRIMARY KEY, hits INTEGER);
CREATE TABLE users (what TEXT PRIMARY KEY, hits INTEGER);

INSERT INTO connections VALUES
    ('2026-10-01 08:15:00.123456', 'unix:/local', 'allow', 'tcp', '192.0.2.1',
     '40001', '203.0.113.5', 'svc.example.com', '443', '1000', '2001',
     '/usr/bin/test-app', '/usr/bin/test-app --sample', '/home/test-user',
     'allow-test-app'),
    ('2026-10-01 08:16:00', 'unix:/local', 'deny', 'udp', '192.0.2.1',
     '40002', '198.51.100.7', 'api.example.net', '53', '1000', '2002',
     '/usr/local/bin/test-agent', '/usr/local/bin/test-agent', '/home/demo-user',
     'deny-test-agent'),
    ('2026-10-01 08:17:30.500000', 'unix:/local', 'allow', 'tcp', '2001:db8::1',
     '40003', '2001:db8::5', '', '8443', '1000', '2003',
     '/usr/bin/test-app', '/usr/bin/test-app', '/home/test-user',
     'allow-test-app');

INSERT INTO nodes VALUES
    ('unix:/local', 'node1.example.com', '1.6.9', '1 day, 2:03:04', '2',
     '4242', '17', '1.6.9', '✓ online', '2026-10-01 08:17:30');

INSERT INTO rules VALUES
    ('2026-10-01 08:00:00', 'unix:/local', 'allow-test-app', 'True', 'False',
     'allow', 'always', 'simple', 'False', 'process.path', '/usr/bin/test-app',
     'Synthetic rule for the collector tests', 'False', '2026-10-01 08:00:00'),
    ('2026-10-01 08:00:05', 'unix:/local', 'deny-test-agent', 'True', 'True',
     'deny', 'always', 'simple', 'False', 'process.path',
     '/usr/local/bin/test-agent', 'Synthetic rule for the collector tests',
     'False', '2026-10-01 08:00:05');

INSERT INTO sockets VALUES
    ('1', '2026-10-01 08:15:01', 'unix:/local', '40001', '192.0.2.1',
     '203.0.113.5', '443', 'tcp', '1000', '123456', '0', 'AF_INET',
     'ESTABLISHED', '0', '0', '0', '0', '0', '0', '0', '2001', 'test-app',
     '/usr/bin/test-app');

INSERT INTO alerts VALUES
    ('2026-10-01 08:20:00', 'unix:/local', 'warning', 'none', 'low',
     'generic', 'Synthetic alert for the collector tests', 'new');

INSERT INTO hosts VALUES ('svc.example.com', 987654321), ('api.example.net', 876543210),
    ('other.example.com', 765432109);
INSERT INTO procs VALUES ('/usr/bin/test-app', 987654321),
    ('/usr/local/bin/test-agent', 876543210);
INSERT INTO addrs VALUES ('203.0.113.5', 987654321), ('198.51.100.7', 876543210),
    ('2001:db8::5', 765432109);
INSERT INTO ports VALUES ('443', 987654321), ('53', 876543210), ('8443', 765432109);
INSERT INTO users VALUES ('1000', 987654321);
