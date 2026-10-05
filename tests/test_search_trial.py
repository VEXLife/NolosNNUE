"""Data thinning must not discard discoveries or leak games across the split."""
import unittest
from trainer.sampling import thin_samples, board_rows


class SamplingTests(unittest.TestCase):
    def sample(self, ply, side, score, game=0):
        return dict(seed=1, game=game, size=15, rule=0, side=side,
                    board='1' * ply + '0' * (225 - ply), score=score)

    def test_board_rows_preserve_black_first_and_absolute_colors(self):
        # Cell scan order begins with white and could falsely appear chronological.
        sample = dict(board='210' + '0' * 222, side=1)
        self.assertEqual(board_rows(sample), ['1,0,1', '0,0,2'])
        sample = dict(board='211' + '0' * 222, side=2)
        self.assertEqual(board_rows(sample), ['1,0,2', '0,0,1', '2,0,2'])
        with self.assertRaises(ValueError):
            board_rows(dict(board='211' + '0' * 222, side=1))

    def test_alternating_side_same_winner_is_one_mate_run(self):
        rows = [self.sample(6, 1, 100), self.sample(7, 2, -29982),
                self.sample(8, 1, 29983), self.sample(9, 2, -29984),
                self.sample(10, 1, 29985)]
        self.assertEqual(thin_samples(rows), rows[:3])

    def test_new_discovery_and_changed_winner_restart_run(self):
        rows = [self.sample(6, 1, 29980), self.sample(7, 2, -29981),
                self.sample(8, 1, 29982), self.sample(9, 2, 30),
                self.sample(10, 1, 29980), self.sample(11, 2, -29981),
                self.sample(12, 1, -29982)]
        self.assertEqual(thin_samples(rows), rows[:2] + rows[3:])

    def test_parallel_write_order_and_games_do_not_change_selection(self):
        rows = [self.sample(p, p % 2 + 1, 29980 if p % 2 == 0 else -29980, game)
                for game in range(2) for p in range(6, 11)]
        kept = thin_samples(rows[::-1])
        self.assertEqual([s['game'] for s in kept], [0, 0, 1, 1])
        self.assertEqual([225-s['board'].count('0') for s in kept], [6, 7, 6, 7])


if __name__ == '__main__':
    unittest.main()
