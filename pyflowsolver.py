from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime
from functools import reduce

import itertools
import operator
import os
import pycosat
import sys

LEFT = 1
RIGHT = 2
TOP = 4
BOTTOM = 8

DELTAS = [(LEFT, 0, -1),
          (RIGHT, 0, 1),
          (TOP, -1, 0),
          (BOTTOM, 1, 0)]

LR = LEFT | RIGHT
TB = TOP | BOTTOM
TL = TOP | LEFT
TR = TOP | RIGHT
BL = BOTTOM | LEFT
BR = BOTTOM | RIGHT

DIR_TYPES = [LR, TB, TL, TR, BL, BR]

DIR_FLIP = {
    LEFT: RIGHT,
    RIGHT: LEFT,
    TOP: BOTTOM,
    BOTTOM: TOP
}


######################################################################


def all_pairs(collection):
    ''' Return all combinations of two items from a collection, useful for
        making a large number of SAT variables mutually exclusive.
    '''

    return itertools.combinations(collection, 2)

######################################################################


def no_two(satvars):
    ''' Given a collection of SAT variables, generates clauses specifying
        that no two of them can be true at the same time.
    '''

    return ((-a, -b) for (a, b) in all_pairs(satvars))

######################################################################


def explode(puzzle):
    ''' Iterator helper function to allow looping over 2D arrays without
        nested 'for' loops.
    '''

    for i, row in enumerate(puzzle):
        for j, char in enumerate(row):
            yield i, j, char

######################################################################


def valid_pos(size, i, j):
    ''' Check whether a position on a square grid is valid.'''
    return i >= 0 and i < size and j >= 0 and j < size

######################################################################


def all_neighbors(i, j):
    ''' Return all neighbors of a grid square at row i, column j.'''
    return ((dir_bit, i + delta_i, j + delta_j)
            for (dir_bit, delta_i, delta_j) in DELTAS)

######################################################################


def valid_neighbors(size, i, j):
    ''' Return all actual on-grid neighbors of a grid square at row i,
        column j.'''

    return ((dir_bit, ni, nj) for (dir_bit, ni, nj)
            in all_neighbors(i, j)
            if valid_pos(size, ni, nj))

######################################################################


def repair_colors(puzzle, colors):
    ''' If the puzzle file used "color labels" (A,B,C...), instead
        of color mnemonics (R,G,B...), convert the labels to mnemonics.
        Note: If a puzzle is in mnemonic format, it will contain the
        letter 'R' since Red is always the first color. Absence of an 'R'
        is the test for a color-labeled puzzle.
    '''
    if 'R' in colors.keys():
        return puzzle, colors

    color_lookup = 'RBYGOCMmPAWgTbcp'
    new_puzzle = []

    try:

        for row in puzzle:

            new_row = []

            for char in row:
                if char.isalnum():
                    char = color_lookup[ord(char) - ord('A')]
                new_row.append(char)

            new_puzzle.append(''.join(new_row))

        new_colors = dict((color_lookup[ord(char) - ord('A')], index)
                          for (char, index) in colors.items())

    except IndexError:
        return puzzle, colors

    return new_puzzle, new_colors

######################################################################


def parse_puzzle(raw_puzzle: list[list[str]]):
    ''' Convert the given string or file object into a square array of
        strings. Also return a dictionary which maps input characters to color
        indices.
    '''
    # truncate extraneous lines

    # count colors and build lookup
    colors = dict()
    color_count = []
    size = len(raw_puzzle[0])
    for i, row in enumerate(raw_puzzle):
        if len(row) != size:
            return None, None
        for j, char in enumerate(row):
            if char.isalnum():  # flow endpoint
                if char in colors:
                    color = colors[char]
                    if color_count[color]:
                        return None, None
                    color_count[color] = 1
                else:
                    color = len(colors)
                    colors[char] = color
                    color_count.append(0)

    # check parity
    for char, color in colors.items():
        if not color_count[color]:
            print(f'color {char} has start but no end!')
            return None, None

    raw_puzzle, colors = repair_colors(raw_puzzle, colors)
    return raw_puzzle, colors

######################################################################


def make_color_clauses(puzzle, colors, color_var):
    ''' Generate CNF clauses entailing the N*M color SAT variables, where N
        is the number of cells and M is the number of colors. Each cell
        encodes a single color in a one-hot fashion.
    '''

    clauses = []
    num_colors = len(colors)
    size = len(puzzle)

    # for each cell
    for i, j, char in explode(puzzle):

        if char.isalnum():  # flow endpoint

            endpoint_color = colors[char]

            # color in this cell is this one
            clauses.append([color_var(i, j, endpoint_color)])

            # color in this cell is not the other ones
            for other_color in range(num_colors):
                if other_color != endpoint_color:
                    clauses.append([-color_var(i, j, other_color)])

            # gather neighbors' variables for this color
            neighbor_vars = [color_var(ni, nj, endpoint_color) for
                             _, ni, nj in valid_neighbors(size, i, j)]

            # one neighbor has this color
            clauses.append(neighbor_vars)

            # no two neighbors have this color
            clauses.extend(no_two(neighbor_vars))

        else:

            # one of the colors in this cell is set
            clauses.append([color_var(i, j, color)
                            for color in range(num_colors)])

            # no two of the colors in this cell are set
            cell_color_vars = (color_var(i, j, color) for
                               color in range(num_colors))

            clauses.extend(no_two(cell_color_vars))

    return clauses

######################################################################


def make_dir_vars(puzzle, start_var):
    ''' Creates the direction-type SAT variables for each cell.'''

    size = len(puzzle)
    dir_vars = dict()
    num_dir_vars = 0

    for i, j, char in explode(puzzle):

        if char.isalnum():  # flow endpoint, no dir needed
            continue

        # collect bits for neighbors (TOP BOTTOM LEFT RIGHT)
        neighbor_bits = (dir_bit for (dir_bit, ni, nj)
                         in valid_neighbors(size, i, j))

        # OR them all together
        cell_flags = reduce(operator.or_, neighbor_bits, 0)

        # create a lookup for dir type vars in this cell
        dir_vars[i, j] = dict()

        for code in DIR_TYPES:
            # only add var if cell has correct flags (i.e. if cell has
            # TOP, BOTTOM, RIGHT, don't add LR).
            if cell_flags & code == code:
                num_dir_vars += 1
                dir_vars[i, j][code] = start_var + num_dir_vars

    return dir_vars, num_dir_vars

######################################################################


def make_dir_clauses(puzzle, colors, color_var, dir_vars):
    ''' Generate clauses involving the color and direction-type SAT
        variables. Each free cell must be exactly one direction, and
        directions imply color matching with neighbors.
    '''

    dir_clauses = []
    num_colors = len(colors)
    size = len(puzzle)

    # for each cell
    for i, j, char in explode(puzzle):

        if char.isalnum():  # flow endpoint, no dir needed
            continue

        cell_dir_dict = dir_vars[(i, j)]
        cell_dir_vars = cell_dir_dict.values()

        # at least one direction is set in this cell
        dir_clauses.append(cell_dir_vars)

        # no two directions are set in this cell
        dir_clauses.extend(no_two(cell_dir_vars))

        # for each color
        for color in range(num_colors):

            # get color var for this cell
            color_1 = color_var(i, j, color)

            # for each neighbor
            for dir_bit, n_i, n_j in all_neighbors(i, j):

                # get color var for other cell
                color_2 = color_var(n_i, n_j, color)

                # for each direction variable in this scell
                for dir_type, dir_var in cell_dir_dict.items():

                    # if neighbor is hit by this direction type
                    if dir_type & dir_bit:
                        # this direction type implies the colors are equal
                        dir_clauses.append([-dir_var, -color_1, color_2])
                        dir_clauses.append([-dir_var, color_1, -color_2])
                    elif valid_pos(size, n_i, n_j):
                        # neighbor is not along this direction type,
                        # so this direction type implies the colors are not equal
                        dir_clauses.append([-dir_var, -color_1, -color_2])

    return dir_clauses

######################################################################


def reduce_to_sat(puzzle, colors):
    ''' Reduces the given puzzle to a SAT problem specified in CNF. Returns
        a list of clauses where each clause is a list of single SAT variables,
        possibly negated.
    '''

    size = len(puzzle)
    num_colors = len(colors)

    num_cells = size**2
    num_color_vars = num_colors * num_cells

    def color_var(i, j, color):
        ''' Return the index of the SAT variable for the given color in row i,
            column j.
        '''
        return (i * size + j) * num_colors + color + 1

    start = datetime.now()

    color_clauses = make_color_clauses(puzzle,
                                       colors,
                                       color_var)

    dir_vars, num_dir_vars = make_dir_vars(puzzle, num_color_vars)

    dir_clauses = make_dir_clauses(puzzle, colors,
                                   color_var, dir_vars)

    num_vars = num_color_vars + num_dir_vars
    clauses = color_clauses + dir_clauses

    reduce_time = (datetime.now() - start).total_seconds()

    return color_var, dir_vars, num_vars, clauses, reduce_time

######################################################################


def decode_solution(puzzle, colors, color_var, dir_vars, sol):
    ''' Takes the solution set from SAT and decodes it by undoing the
        one-hot encoding in each cell for color and direction-type. Returns a
        2D array of (color, direction-type) pairs.
    '''

    sol = set(sol)

    decoded = []

    for i, row in enumerate(puzzle):

        decoded_row = []

        for j, char in enumerate(row):

            # find which color variable for this cell is in the
            # solution set
            cell_color = -1

            for color in range(len(colors)):
                if color_var(i, j, color) in sol:
                    assert cell_color == -1
                    cell_color = color

            assert cell_color != -1

            cell_dir_type = -1

            if not char.isalnum():  # not a flow endpoint

                # find which dir type variable for this cell is in the
                # solution set
                for dir_type, dir_var in dir_vars[i, j].items():
                    if dir_var in sol:
                        assert cell_dir_type == -1
                        cell_dir_type = dir_type

                assert cell_dir_type != -1
            decoded_row.append((cell_color, cell_dir_type))

        decoded.append(decoded_row)
    return decoded

######################################################################


def make_path(decoded, visited, cur_i, cur_j):
    '''Follow a path starting from an arbitrary row, column location on
the grid until a non-path cell is detected, or a cycle is
found. Returns a list of (row, column) pairs on the path, as well as a
boolean flag indicating if a cycle was detected.
    '''

    size = len(decoded)

    run = []
    is_cycle = False
    prev_i, prev_j = -1, -1

    while True:

        advanced = False

        # get current cell, set visited, add to path
        color, dir_type = decoded[cur_i][cur_j]
        visited[cur_i][cur_j] = 1
        run.append((cur_i, cur_j))

        # loop over valid neighbors
        for dir_bit, n_i, n_j in valid_neighbors(size, cur_i, cur_j):

            # do not consider prev pos
            if (n_i, n_j) == (prev_i, prev_j):
                continue

            # get neighbor color & dir type
            n_color, n_dir_type = decoded[n_i][n_j]

            # these are connected if one of the two dir type variables
            # includes the (possibly flipped) direction bit.
            if ((dir_type >= 0 and (dir_type & dir_bit)) or
                    (dir_type == -1 and n_dir_type >= 0 and
                     n_dir_type & DIR_FLIP[dir_bit])):

                # if connected, they better be the same color
                assert color == n_color

                # detect cycle
                if visited[n_i][n_j]:
                    is_cycle = True
                else:
                    prev_i, prev_j = cur_i, cur_j
                    cur_i, cur_j = n_i, n_j
                    advanced = True

                # either cycle detected or path advanced, so stop
                # looking at neighbors
                break

        # if path not advanced, quit
        if not advanced:
            break

    return run, is_cycle

######################################################################


def detect_cycles(decoded, dir_vars):
    '''Examine the decoded SAT solution to see if any cycles exist; if so,
return the CNF clauses that need to be added to the problem in order
to prevent them.
    '''

    size = len(decoded)
    colors_seen = set()
    visited = [[0] * size for _ in range(size)]

    # for each cell
    for i, j, (color, dir_type) in explode(decoded):

        # if flow endpoint for color we haven't dealt with yet
        if dir_type == -1 and color not in colors_seen:

            # add it to set of colors dealt with
            assert not visited[i][j]
            colors_seen.add(color)

            # mark the path as visited
            run, is_cycle = make_path(decoded, visited, i, j)
            assert not is_cycle

    # see if there are any unvisited cells, if so they have cycles
    extra_clauses = []

    for i, j in itertools.product(range(size), range(size)):

        if not visited[i][j]:

            # get the path
            run, is_cycle = make_path(decoded, visited, i, j)
            assert is_cycle

            # generate a clause negating the conjunction of all
            # direction types along the cycle path.
            clause = []

            for r_i, r_j in run:
                _, dir_type = decoded[r_i][r_j]
                dir_var = dir_vars[r_i, r_j][dir_type]
                clause.append(-dir_var)

            extra_clauses.append(clause)

    # return whatever clauses we had to generate
    return extra_clauses

######################################################################


def solve_sat(puzzle, colors, color_var, dir_vars, clauses):
    '''Solve the SAT now that it has been reduced to a list of clauses in
CNF.  This is an iterative process: first we try to solve a SAT, then
we detect cycles. If cycles are found, they are prevented from
recurring, and the next iteration begins. Returns the decoded puzzle solution.
    '''

    while True:

        sol = pycosat.solve(clauses)
        decoded = decode_solution(puzzle, colors, color_var, dir_vars, sol)

        extra_clauses = detect_cycles(decoded, dir_vars)

        if not extra_clauses:
            break

    return decoded

######################################################################


def pyflow_solver_main(raw_puzzle: list[list[str]]) -> list[int]:
    '''This function is what starts the process of solving the puzzle.'''

    puzzle, colors = parse_puzzle(raw_puzzle)
    color_var, dir_vars, num_vars, clauses, reduce_time = reduce_to_sat(
        puzzle, colors)

    solution = solve_sat(puzzle, colors,
                         color_var, dir_vars, clauses)
    return solution
