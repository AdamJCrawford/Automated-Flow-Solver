# Automated-Flow-Solver

The original solver that I modified can be found here:https://github.com/mzucker/flow_solver
I updated the code so it can be run with Python3 as well as removed code that wasn't being used.

The pycosat module can be found here: https://github.com/conda/pycosat

The program works by taking a screenshot on the connected device. The device should be on the screen that contains the puzzle you want to solve. As it currently stands, the program is very sensitive to the background color. You may have to run it a few times for the program to work as intended. The program cannot handle non-square puzzles. Also, type hints as well as comments in the “main.py” file are not fully implemented yet.
