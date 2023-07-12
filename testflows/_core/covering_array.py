# Copyright 2023 Katteli Inc.
# TestFlows.com Open-Source Software Testing Framework (http://testflows.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import math

from collections import namedtuple
from itertools import product, islice, combinations


class CoveringArrayError(Exception):
    """Covering array error."""

    def __init__(self, combination, values):
        self.combination = combination
        self.values = values

    def __str__(self):
        return f"missing combination={self.combination},values={self.values}"


class X:
    """Don't care value."""

    pass


BestTest = namedtuple("BestTest", "test coverage bitmap")
Π = namedtuple("Π", "combinations bitmap")


def prepare(parameters):
    """Returns parameters set and its map.

    Parameters set is a list[list] where
    first level is indexed keys and second level
    are indexed values for a given parameter.

    Parameters map can be used to convert keys and values
    indexes to actual parameters name and values.

    :param parameters: parameters dictionary dict[str, list[values]])
    """
    keys = list(parameters.keys())

    parameters_set = []
    parameters_map = {}

    for key in keys:
        v = parameters[key]
        v = list(set(v))
        parameters_map[key] = v
        parameters_set.append(list(range(len(v))))

    return parameters_set, parameters_map


def combination_index(t, N, combination):
    """Return an index for a given combination in π.
    Combination is represented by a tuple containing
    parameters referenced by their indexes.

    https://stackoverflow.com/questions/37764429/algorithm-for-combination-index-in-array

    f(5, 3, [2,3,4]) = binom(5,3) - binom(5-2,3) - binom(5-3,2) - binom(5-4,1) =
                     = 10 - 1 - 1 - 1 = 6

    :param combination: tuple(parameter index,...)
    """

    t -= 1
    index = math.comb(N, t) - 1
    for i, p in enumerate(combination[:-1]):
        p += 1
        index -= math.comb(N - p, t - i)

    return index


def combination_values_bitmap_index(combination, values, parameters_set):
    """Return an bit index in the bitmap for a given
    parameter combination and the specific combination of values
    for these parameters.

    Example:
    ```
    >>> for j,i in enumerate(list(itertools.product([0,1,2,3],[0,1,2],[0,1,2]))):
    ...    print(i, 9*i[0] + 3*i[1] + 1*i[2], j)
    [0,1,2,3],[0,1,2],[0,1,2]
    i         j       k
    Jv * Kv = 9
    Kv = 3
    1
    ```

    :param combination: combination of parameters
    :param values: specific combination of values for the parameters
    """
    value_lengths = [len(parameters_set[p]) for p in combination]

    index = 0
    for i, value in enumerate(values):
        index += math.prod(value_lengths[i + 1 :]) * value
    return index


def bitmap_index_combination_values(index, combination, parameters_set):
    """Return values for a given bitmap index and
    combination of parameters.

    Example:
    ```
    (3, 1, 1) 15 15
     5  2  2

    4*i[0] + 2*i[1] + 1*i[2] = 15
    = 15//4 = 3 (15-12) = 3
    = 3//2 = 1 (3 - 2) = 1
    = 1//1 = 1
    = (3,1,1)
    ```

    :param index: bitmap index
    :param combination: combination of parameters
    """
    value_lengths = [len(parameters_set[p]) for p in combination]

    value = [0] * len(combination)

    c = index
    for i in range(len(combination)):
        j = math.prod(value_lengths[i + 1 :])
        value[i] = c // j
        c = c - value[i] * j

    return value


def construct_π(i, t, parameters_set):
    """Construct a set t-way combinations of values
    involving parameter Pi and t-1 parameters among
    the first i-1 parameters.

    Return pi which is a dictionary of bitmaps where each bit
    represent if parameter value combination is covered (0) or not (1).

    Initially, the bitmap is set to all 1's.
    """
    # create all t-way combinations of Pi with P0 to Pi-1 columns
    t_way_combinations = [c + (i,) for c in combinations(range(i), t - 1)]

    # FIXME: value_lengths should be stored
    # FIXME: value coefficients should be stored
    π = Π(
        t_way_combinations,
        [
            (1 << math.prod([len(parameters_set[p]) for p in combination])) - 1
            for combination in t_way_combinations
        ],
    )
    return π


def horizontal_extension(t, i, tests, π, parameters_set):
    """Horizontal extension for parameter Pi."""

    # for each test τ = (v1, v2, …, vi-1) in tests
    for τ in range(len(tests)):
        test = tests[τ]
        # choose a value vi of Pi and replace τ with τ’ = (v1, v2, …, vi-1, vi) so that τ’ covers the
        # most number of combinations of values in π
        best = None
        # FIXME: if bitmap is all empty set value to don't care and don't try to pick any value

        for value in parameters_set[i]:
            new_test = test + [value]
            coverage, bitmap = calculate_coverage(t, i, new_test, π, parameters_set)
            if best is None or coverage >= best.coverage:
                best = BestTest(new_test, coverage, bitmap)
        tests[τ] = best.test
        π = Π(π.combinations, best.bitmap)

    return tests, π


def vertical_extension(t, i, tests, π, parameters_set):
    """Vertical extension for parameter Pi"""

    # for each combination of σ in π
    for combination in π.combinations:
        index = combination_index(t, i, combination)

        bitmap = π.bitmap[index]
        bitmap_index = -1

        if bitmap == 0:
            continue

        while bitmap:
            bitmap_index += 1
            if not bitmap & 1:
                bitmap >>= 1
                continue
            bitmap >>= 1

            values = bitmap_index_combination_values(
                bitmap_index, combination, parameters_set
            )

            covered = False

            for test in tests:
                test_values = combination_values(test, combination)
                if values == test_values:
                    # already covered
                    covered = True
                    break

                # not covered, so either change an existing test, if possible
                change_existing = True
                for value, test_value in zip(values, test_values):
                    if value == test_value:
                        continue
                    elif test_value is X:
                        continue
                    else:
                        change_existing = False

                if change_existing:
                    set_combination_values(test, values, combination)
                    covered = True
                    break

            if covered:
                # move to the next combination of values
                continue

            # or otherwise add a new test to cover σ and remove it from π
            new_test = [X] * len(parameters_set[: i + 1])
            set_combination_values(new_test, values, combination)
            tests.append(new_test)

    # replace all X with the first value for a given parameter
    for test in tests:
        for i, p in enumerate(test):
            if p is not X:
                continue
            test[i] = parameters_set[i][0]

    return tests


def convert_tests_to_covering_array(tests, parameters_map):
    """Convert tests to covering array.

    Covering array is a list of tests where each test
    is a dictionary of parameter names to values list[dict(name, value)]
    where tests exhaustively cover a chosen level of t-way combinations of
    parameters.

    Example:
       Parameters map:  {'a': [1, 2], 'b': ['b', 'd', 'c', 'a'], 'c': [10]}

    """
    ca = []
    parameter_names = list(parameters_map.keys())

    for test in tests:
        ca_test = {}
        for i, p in enumerate(test):
            parameter_name = parameter_names[i]
            ca_test[parameter_name] = parameters_map[parameter_name][p]
        ca.append(ca_test)

    return ca


def combination_values(test, combination):
    """Return values of the combination covered by a given test."""
    values = [0] * len(combination)

    for i, parameter in enumerate(combination):
        values[i] = test[parameter]

    return values


def set_combination_values(test, values, combination):
    """Set test values for a given combination."""
    for i, parameter in enumerate(combination):
        test[parameter] = values[i]


def calculate_coverage(t, i, test, π, parameters_set):
    """Calculate coverage of the test for a given π combinations."""
    coverage = 0

    new_bitmap = list(π.bitmap)

    for combination in π.combinations:
        index = combination_index(t, i, combination)
        bitmap = π.bitmap[index]

        current_coverage = (bitmap).bit_count()

        values = combination_values(test, combination)

        bitmap_index = combination_values_bitmap_index(
            combination, values, parameters_set
        )

        bitmap = bitmap & ~(1 << bitmap_index)
        new_coverage = (bitmap).bit_count()
        coverage += current_coverage - new_coverage

        new_bitmap[index] = bitmap

    return coverage - current_coverage, new_bitmap


def covering_array(parameters, strength=2):
    """Generate covering array of specified `strength`
    for the given `parameters` where parameters
    is a dict[str, list[value]] where key is the parameter name,
    value is a list of values for a given parameter.

    Uses an algorithm described in the following paper

    2007, "IPOG: A General Strategy for T-Way Software Testing" by
    Yu Lei1, Raghu Kacker, D. Richard Kuhn, Vadim Okun, and James Lawrence

    :param parameters: parameters (dict[str, list[values]])
    :param strength: (optional) strength, default: 2
    """
    # t-strength is > 1 and <= number of parameters
    t = max(1, min(strength, len(parameters)))

    # convert parameters dictionary into a parameters set
    # which uses only indexes for parameter names and values
    parameters_set, parameters_map = prepare(parameters)

    # construct first tests using all possible combinations of values
    # for the first t-strength parameters
    tests = list(product(*parameters_set[:t]))

    for i in range(len(tests)):
        tests[i] = list(tests[i])

    for i in range(t, len(parameters_set)):
        π = construct_π(i=i, t=t, parameters_set=parameters_set)
        tests, π = horizontal_extension(t, i, tests, π, parameters_set)
        tests = vertical_extension(t, i, tests, π, parameters_set)

    return convert_tests_to_covering_array(tests, parameters_map)


def check(parameters, covering_array, strength=2):
    """Returns True if covering array covers all t-strength
    combination of the parameters or raises an error."""
    t = strength

    if not covering_array:
        raise ValueError("covering array is empty")

    parameter_names = list(parameters.keys())

    for combination in combinations(parameter_names, strength):
        for values in product(*[parameters[parameter] for parameter in combination]):
            covered = True
            for test in covering_array:
                covered = True
                for i, parameter in enumerate(combination):
                    if test[parameter] != values[i]:
                        covered = False
                        break
                if covered:
                    break
            if not covered:
                raise CoveringArrayError(combination, values)

    return True


def dump(ca):
    """Dump covering array representation to string."""
    lines = [f"{len(ca)}"]
    header = " ".join(str(v) for v in ca[0].keys())

    lines.append(header)
    lines.append("-" * len(header))

    for test in ca:
        lines.append(" ".join(str(v) for v in test.values()))

    return "\n".join(lines)


if __name__ == "__main__":
    t = 2
    k = 4
    v = 3
    parameters = {}
    for i in range(k):
        parameters[i] = list(range(v))

    ca = covering_array(parameters=parameters, strength=t)
    assert check(parameters, ca, t), "generated invalid covering array"
    print(dump(ca))
