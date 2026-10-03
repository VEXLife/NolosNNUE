import unittest
from scripts.match_external import winning, observed_qualification


class ExternalMatchTests(unittest.TestCase):
    def test_freestyle_overline_and_each_direction(self):
        for dx, dy in [(1, 0), (0, 1), (1, 1), (1, -1)]:
            cells = [0] * 225
            x, y = 4, 9 if dy == -1 else 4
            for k in range(6):
                cells[(y + k * dy) * 15 + x + k * dx] = 2
            self.assertTrue(winning(cells, 15, x, y, 2))
            self.assertFalse(winning(cells, 15, x, y, 1))

    def test_gap_and_boundary_do_not_wrap_rows(self):
        cells = [0] * 225
        for p in [12, 13, 14, 15, 16]:
            cells[p] = 1
        self.assertFalse(winning(cells, 15, 14, 0, 1))
        cells = [0] * 225
        for p in [101, 102, 104, 105]:
            cells[p] = 1
        self.assertFalse(winning(cells, 15, 11, 6, 1))

    def test_one_white_win_disqualifies_and_errors_are_inconclusive(self):
        black = dict(status='complete', winner=1)
        white = dict(status='complete', winner=2)
        self.assertFalse(observed_qualification([black, white], 2))
        self.assertTrue(observed_qualification([black, black], 2))
        for other in [dict(status='truncated', winner=None), dict(status='error', winner=None),
                      dict(status='complete', winner=0)]:
            self.assertIsNone(observed_qualification([black, other], 2))
        self.assertIsNone(observed_qualification([black], 2))


if __name__ == '__main__':
    unittest.main()
