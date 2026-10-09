"""STRM 电影删除时的转移记录匹配回归测试。"""

import ast
import unittest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "plugins.v2/samediasyncdel/__init__.py"


class MediaType(Enum):
    MOVIE = "电影"
    TV = "电视剧"


@dataclass
class TransferHistory:
    tmdbid: int
    mtype: str
    dest: str


class TransferHistoryOper:
    def __init__(self, records):
        self.records = records

    def get_by(self, **criteria):
        return [
            record
            for record in self.records
            if all(getattr(record, key) == value for key, value in criteria.items())
        ]


class Logger:
    def info(self, message):
        pass

    def warning(self, message):
        pass


def load_lookup_method():
    tree = ast.parse(PLUGIN_PATH.read_text(encoding="utf-8"))
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SaMediaSyncDel"
    )
    method = next(
        node for node in plugin_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__get_transfer_his"
    )
    isolated = ast.ClassDef(
        name="SaMediaSyncDel", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    module = ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[]))
    scope = {
        "MediaType": MediaType,
        "TransferHistory": TransferHistory,
        "List": list,
        "Path": Path,
        "settings": SimpleNamespace(RMT_MEDIAEXT=[".mkv", ".mp4"]),
        "logger": Logger(),
    }
    exec(compile(module, str(PLUGIN_PATH), "exec"), scope)
    return scope["SaMediaSyncDel"]


class StrmMovieHistoryTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_lookup_method()()
        self.strm_path = "/CD2/115/影视库/电影/木乃伊 (2026)/木乃伊.strm"
        self.movie_path = "/CD2/115/影视库/电影/木乃伊 (2026)/木乃伊.mkv"

    def lookup(self, path, strm_movie=False, tmdb_id=1304313):
        return self.plugin._SaMediaSyncDel__get_transfer_his(
            media_type="Movie",
            media_name="木乃伊 (2026)",
            media_path=path,
            tmdb_id=tmdb_id,
            season_num=None,
            episode_num=None,
            strm_movie=strm_movie,
        )[1]

    def test_local_strm_matches_only_history_in_same_directory(self):
        expected = TransferHistory(1304313, MediaType.MOVIE.value, self.movie_path)
        self.plugin._transferhis = TransferHistoryOper([expected])

        self.assertEqual(self.lookup(self.strm_path), [expected])

    def test_cloud_strm_matches_renamed_media_file(self):
        expected = TransferHistory(
            1304313, MediaType.MOVIE.value,
            str(Path(self.movie_path).with_name("木乃伊.2026.2160p.mkv")),
        )
        self.plugin._transferhis = TransferHistoryOper([expected])

        self.assertEqual(self.lookup(self.movie_path, strm_movie=True), [expected])

    def test_normal_movie_path_remains_exact(self):
        expected = TransferHistory(1304313, MediaType.MOVIE.value, self.movie_path)
        other = TransferHistory(
            1304313, MediaType.MOVIE.value,
            str(Path(self.movie_path).with_name("木乃伊.另一版本.mkv")),
        )
        self.plugin._transferhis = TransferHistoryOper([expected, other])

        self.assertEqual(self.lookup(self.movie_path), [expected])

    def test_multiple_versions_are_ambiguous(self):
        first = TransferHistory(1304313, MediaType.MOVIE.value, self.movie_path)
        second = TransferHistory(
            1304313, MediaType.MOVIE.value,
            str(Path(self.movie_path).with_name("木乃伊.另一版本.mkv")),
        )
        self.plugin._transferhis = TransferHistoryOper([first, second])

        self.assertEqual(self.lookup(self.strm_path), [])

    def test_different_directory_or_tmdb_does_not_match(self):
        other_dir = TransferHistory(
            1304313, MediaType.MOVIE.value,
            "/CD2/115/影视库/电影/其他电影/木乃伊.mkv",
        )
        other_tmdb = TransferHistory(42, MediaType.MOVIE.value, self.movie_path)
        self.plugin._transferhis = TransferHistoryOper([other_dir, other_tmdb])

        self.assertEqual(self.lookup(self.strm_path), [])

    def test_missing_tmdb_does_not_use_fallback(self):
        history = TransferHistory(None, MediaType.MOVIE.value, self.movie_path)
        self.plugin._transferhis = TransferHistoryOper([history])

        self.assertEqual(self.lookup(self.strm_path, tmdb_id=None), [])

    def test_windows_separators_match_same_directory(self):
        strm_path = r"D:\media\木乃伊 (2026)\木乃伊.strm"
        history = TransferHistory(
            1304313, MediaType.MOVIE.value,
            r"D:\media\木乃伊 (2026)\木乃伊.mkv",
        )
        self.plugin._transferhis = TransferHistoryOper([history])

        self.assertEqual(self.lookup(strm_path), [history])


if __name__ == "__main__":
    unittest.main()
