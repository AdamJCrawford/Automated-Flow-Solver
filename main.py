import numpy as np
import pyflowsolver
import skimage

from PIL import Image
from ppadb.client import Client


def draw_paths(device, paths: list[list[list[int]]], indicies: dict[tuple[float]:list[str, int, int]], pixel_grid_boarder_indices: list[int], grid_cell_height: int, grid_length: int, grid_height: int) -> None:
    for i, value in enumerate(indicies.values()):
        if len(value) != 1:
            initial_x = pixel_grid_boarder_indices[value[1]] + \
                grid_cell_height // 2
            initial_y = value[2] * grid_cell_height + grid_cell_height // 2

            for part in paths[i - 1]:
                end_x = initial_x + part[0] * grid_cell_height

                end_y = initial_y + part[1] * grid_cell_height

                device.shell(
                    f"input touchscreen swipe {initial_y} {initial_x} {end_y} {end_x} 10")
                initial_x = end_x
                initial_y = end_y


def search(grid: list[tuple[int]], curr_path: list[list[int]], indices_list: list[list[int]], target: int, i: int, j: int):
    if i >= 1:
        if grid[i - 1][j][0] == target and [i - 1, j] not in indices_list:
            curr_path.append([-1, 0])
            indices_list.append([i - 1, j])
            return search(grid, curr_path, indices_list, target, i - 1, j)

    if i < len(grid) - 1:
        if grid[i + 1][j][0] == target and [i + 1, j] not in indices_list:
            curr_path.append([1, 0])
            indices_list.append([i + 1, j])
            return search(grid, curr_path, indices_list, target, i + 1, j)

    if j >= 1:
        if grid[i][j - 1][0] == target and [i, j - 1] not in indices_list:
            curr_path.append([0, -1])
            indices_list.append([i, j - 1])
            return search(grid, curr_path, indices_list, target, i, j - 1)

    if j < len(grid[0]) - 1:
        if grid[i][j + 1][0] == target and [i, j + 1] not in indices_list:
            curr_path.append([0, 1])
            indices_list.append([i, j + 1])
            return search(grid, curr_path, indices_list, target, i, j + 1)

    return curr_path


def get_paths(grid: list[tuple[int]]) -> None:
    already_done = {}
    paths = []
    for i, row in enumerate(grid):
        for j, val in enumerate(row):
            if val[1] == -1 and val[0] not in already_done:
                paths.append(search(grid, [], [[i, j]], val[0], i, j))
                already_done[val[0]] = 1
    return paths


def difference(lab1: tuple[float], lab2: tuple[float]) -> float:
    return ((lab2[0] - lab1[0]) ** 2 + (lab2[1] - lab1[1]) ** 2 + (lab2[2] - lab1[2]) ** 2) ** .5


def main() -> None:
    abd = Client(host='127.0.0.1', port=5037)
    devices = abd.devices()

    if not len(devices):
        print("No devices found")
        quit()

    device = devices[0]

    image = device.screencap()

    with open("puzzle.png", "wb") as f:
        f.write(image)

    image = Image.open("puzzle.png")
    image = np.array(image, dtype=np.uint8)[:, :, :3]

    grid_color = np.array(list(image[749][:3])[2])

    cnt, last_index_cnt = 0, 0
    indices = []
    for i, row in enumerate(image):
        if np.array_equal(grid_color, row[10]):
            if i - last_index_cnt <= 5:
                continue
            last_index_cnt = i
            cnt += 1
            indices.append(i)

    grid_height = cnt - 1

    grid_cell_height = sum([indices[i + 1] - indices[i]
                            for i in range(len(indices) - 1)]) // (cnt - 1)

    grid = [[None] * grid_height for i in range(grid_height)]

    colors_seen = {(0, 0, 0): ['.']}

    for i in range(grid_height):
        for j in range(grid_height):
            i_index = indices[i] + grid_cell_height // 2
            j_index = j * grid_cell_height + grid_cell_height // 2

            curr_pixel = tuple(skimage.color.rgb2lab(
                image[i_index][j_index] / 255))

            for key in colors_seen:
                if difference(curr_pixel, key) < 7 or difference(curr_pixel, (0, 0, 0)) < 10:
                    grid[i][j] = colors_seen[key][0]
                    break
            else:
                colors_seen[curr_pixel] = [
                    chr(ord('@') + len(colors_seen)), i, j]
                grid[i][j] = colors_seen[curr_pixel][0]

    unprocessed_path = pyflowsolver.pyflow_solver_main(grid)

    processed_path = get_paths(unprocessed_path)
    draw_paths(device, processed_path, colors_seen, indices,
               grid_cell_height, grid_height, grid_height)


if __name__ == '__main__':
    main()
