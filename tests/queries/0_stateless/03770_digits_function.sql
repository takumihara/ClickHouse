-- Tests for the digits(n, start, length) function (issue #9077).

SELECT digits(1234567890, 3, 2);
SELECT digits(1234567890, 1, 4);
SELECT digits(1234567890, 1, 10);
SELECT digits(42, 1, 1);
SELECT digits(42, 2, 1);
SELECT digits(0, 1, 1);
SELECT digits(-987, 1, 2);
SELECT digits(1234567890, 5, 100);
SELECT digits(1234567890, 20, 2);
SELECT digits(1234567890, 0, 2);
SELECT digits(1234567890, 3, 0);
SELECT digits(7, 1, 5);

-- over a column
SELECT digits(number * 111 + 100, 1, 2) FROM numbers(3) ORDER BY number;

-- different integer widths and signedness
SELECT digits(toUInt8(255), 1, 2);
SELECT digits(toInt64(-1234567890123456789), 1, 3);
SELECT digits(toUInt64(18446744073709551615), 1, 4);
SELECT digits(toUInt64(18446744073709551615), 1, 20);

-- errors
SELECT digits('abc', 1, 1); -- { serverError ILLEGAL_TYPE_OF_ARGUMENT }
SELECT digits(1.5, 1, 1); -- { serverError ILLEGAL_TYPE_OF_ARGUMENT }
SELECT digits(123); -- { serverError NUMBER_OF_ARGUMENTS_DOESNT_MATCH }
