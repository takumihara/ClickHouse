#include <algorithm>

#include <Columns/ColumnsNumber.h>
#include <Core/Types.h>
#include <DataTypes/DataTypesNumber.h>
#include <DataTypes/IDataType.h>
#include <Functions/FunctionFactory.h>
#include <Functions/FunctionHelpers.h>
#include <Functions/IFunction.h>


namespace DB
{

namespace
{

/// digits(n, start, length)
///
/// Reads a run of decimal digits from the integer `n` and returns them as a
/// single UInt64 number. Digits are counted from the most significant (leftmost)
/// digit, starting at position 1. The function reads `length` digits beginning
/// at position `start`. It is the numeric counterpart of `substring` applied to
/// the decimal representation of an integer.
///
/// The sign of `n` is ignored (the function operates on abs(n)). Positions that
/// fall outside the available digits are skipped; if the requested window does
/// not overlap the number at all, the function returns 0.
///
/// Example: digits(1234567890, 3, 2) = 34.
class FunctionDigits : public IFunction
{
public:
    static constexpr auto name = "digits";

    static FunctionPtr create(ContextPtr) { return std::make_shared<FunctionDigits>(); }

    String getName() const override { return name; }

    size_t getNumberOfArguments() const override { return 3; }

    bool isSuitableForShortCircuitArgumentsExecution(const DataTypesWithConstInfo & /*arguments*/) const override { return true; }

    bool useDefaultImplementationForConstants() const override { return true; }

    DataTypePtr getReturnTypeImpl(const ColumnsWithTypeAndName & arguments) const override
    {
        FunctionArgumentDescriptors args{
            {"n", static_cast<FunctionArgumentDescriptor::TypeValidator>(&isNativeInteger), nullptr, "An integer to read digits from"},
            {"start", static_cast<FunctionArgumentDescriptor::TypeValidator>(&isNativeInteger), nullptr, "1-based position of the first digit, counted from the left"},
            {"length", static_cast<FunctionArgumentDescriptor::TypeValidator>(&isNativeInteger), nullptr, "Number of digits to read"},
        };
        validateFunctionArguments(*this, arguments, args);

        return std::make_shared<DataTypeUInt64>();
    }

    ColumnPtr executeImpl(const ColumnsWithTypeAndName & arguments, const DataTypePtr &, size_t input_rows_count) const override
    {
        const IColumn & col_n = *arguments[0].column;
        const IColumn & col_start = *arguments[1].column;
        const IColumn & col_length = *arguments[2].column;

        const bool n_is_unsigned = WhichDataType(arguments[0].type).isUInt();

        auto col_res = ColumnUInt64::create(input_rows_count);
        auto & res_data = col_res->getData();

        for (size_t i = 0; i < input_rows_count; ++i)
        {
            UInt64 n_abs;
            if (n_is_unsigned)
            {
                n_abs = col_n.getUInt(i);
            }
            else
            {
                const Int64 v = col_n.getInt(i);
                /// Overflow-safe absolute value, including for INT64_MIN.
                n_abs = v < 0 ? static_cast<UInt64>(-(v + 1)) + 1 : static_cast<UInt64>(v);
            }

            res_data[i] = extractDigits(n_abs, col_start.getInt(i), col_length.getInt(i));
        }

        return col_res;
    }

private:
    /// Extract `length` digits of `n` starting at 1-based position `start` (from the left).
    static UInt64 extractDigits(UInt64 n, Int64 start, Int64 length)
    {
        if (length <= 0)
            return 0;

        /// Number of decimal digits in n (1 for n == 0).
        int num_digits = 1;
        for (UInt64 t = n; t >= 10; t /= 10)
            ++num_digits;

        /// Requested window intersected with the available positions [1, num_digits].
        /// Int128 keeps the addition safe for extreme start/length values.
        const Int128 window_end = static_cast<Int128>(start) + static_cast<Int128>(length) - 1;
        const Int64 lo = static_cast<Int64>(std::max<Int128>(start, 1));
        const Int64 hi = static_cast<Int64>(std::min<Int128>(window_end, num_digits));
        if (lo > hi)
            return 0;

        const int drop_right = num_digits - static_cast<int>(hi); /// digits to the right of the window
        const int take = static_cast<int>(hi - lo + 1);           /// digits inside the window, 1..num_digits

        UInt64 value = n;
        for (int k = 0; k < drop_right; ++k)
            value /= 10;

        /// num_digits <= 20, so `take` <= 20. 10^20 does not fit into UInt64, but in that
        /// case the window already covers the whole number and no trimming is needed.
        if (take >= 20)
            return value;

        UInt64 modulus = 1;
        for (int k = 0; k < take; ++k)
            modulus *= 10;

        return value % modulus;
    }
};

}

REGISTER_FUNCTION(Digits)
{
    FunctionDocumentation::Description description = R"(
Reads a run of decimal digits from an integer and returns them as a number.

Digits are counted from the most significant (leftmost) digit, starting at position 1.
The function reads `length` digits beginning at position `start` and returns them as a
single `UInt64`. It is the numeric counterpart of [`substring`](#substring) applied to the
decimal representation of an integer.

The sign of the input is ignored (the function operates on the absolute value). Positions
outside the available digits are skipped; if the requested window does not overlap the number
at all, the function returns `0`.
)";
    FunctionDocumentation::Syntax syntax = "digits(n, start, length)";
    FunctionDocumentation::Arguments arguments = {
        {"n", "The integer to read digits from. Native integer types up to 64 bits are supported.", {"(U)Int8/16/32/64"}},
        {"start", "1-based position of the first digit, counted from the most significant digit.", {"(U)Int*"}},
        {"length", "Number of digits to read.", {"(U)Int*"}},
    };
    FunctionDocumentation::ReturnedValue returned_value = {"The selected digits as a number.", {"UInt64"}};
    FunctionDocumentation::Examples examples = {
        {"Middle digits", "SELECT digits(1234567890, 3, 2)", "34"},
        {"Leading digits", "SELECT digits(1234567890, 1, 4)", "1234"},
        {"Single digit", "SELECT digits(42, 1, 1)", "4"},
    };
    FunctionDocumentation::IntroducedIn introduced_in = {26, 7};
    FunctionDocumentation::Category category = FunctionDocumentation::Category::Arithmetic;
    FunctionDocumentation documentation = {description, syntax, arguments, {}, returned_value, examples, introduced_in, category};

    factory.registerFunction<FunctionDigits>(documentation, FunctionFactory::Case::Sensitive);
}

}
