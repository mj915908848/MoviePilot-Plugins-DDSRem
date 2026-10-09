"""STRM 电影删除时的转移记录匹配回归测试。"""

import ast
import tempfile
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

    def warn(self, message):
        pass


def load_lookup_method():
    tree = ast.parse(PLUGIN_PATH.read_text(encoding="utf-8"))
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SaMediaSyncDel"
    )
    method_names = {
        "has_prefix",
        "__get_local_media_paths",
        "__find_local_transfer_his",
        "__get_transfer_his",
    }
    methods = [
        node for node in plugin_class.body
        if isinstance(node, ast.FunctionDef) and node.name in method_names
    ]
    isolated = ast.ClassDef(
        name="SaMediaSyncDel", bases=[], keywords=[], body=methods, decorator_list=[]
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


class DuplicateLocalMappingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.source = root / "emby" / "影视库"
        self.targets = [root / name / "影视库" for name in ("CD2", "PT", "PT2")]
        self.relative_path = Path("电影/欧美电影/浴血黑帮：不朽传奇 (2026) {tmdb-875828}/movie.strm")
        self.emby_path = str(self.source / self.relative_path)
        self.series_relative_path = Path("电视剧/国产剧/百花杀 (2026) {tmdb-286506}")
        self.series_emby_path = str(self.source / self.series_relative_path)
        self.plugin = load_lookup_method()()
        self.plugin._local_library_path = "\n".join(
            f"{self.source}#{target}" for target in self.targets
        )

    def find(self, media_type="MOV", season_num=None, episode_num=None, media_path=None,
             tmdb_id=875828):
        return self.plugin._SaMediaSyncDel__find_local_transfer_his(
            media_type=media_type,
            media_name="浴血黑帮：不朽传奇 (2026)",
            media_path=media_path or self.emby_path,
            tmdb_id=tmdb_id,
            season_num=season_num,
            episode_num=episode_num,
        )

    def history_at(self, target):
        return TransferHistory(
            875828, MediaType.MOVIE.value,
            str((target / self.relative_path).with_name("浴血黑帮：不朽传奇.Peaky.Blinders.2026.mkv")),
        )

    def test_third_mapping_finds_only_matching_transfer_history(self):
        expected = self.history_at(self.targets[2])
        self.plugin._transferhis = TransferHistoryOper([expected])

        mapped_path, _, histories = self.find()

        self.assertEqual(mapped_path, str(self.targets[2] / self.relative_path))
        self.assertEqual(histories, [expected])

    def test_records_in_multiple_destinations_are_ambiguous(self):
        self.plugin._transferhis = TransferHistoryOper(
            [self.history_at(self.targets[0]), self.history_at(self.targets[2])]
        )

        mapped_path, _, histories = self.find()

        self.assertIsNone(mapped_path)
        self.assertEqual(histories, [])

    def test_strm_filename_selects_one_matching_version(self):
        matching = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[0] / self.relative_path).with_suffix(".mkv")),
        )
        other = self.history_at(self.targets[2])
        self.plugin._transferhis = TransferHistoryOper([matching, other])

        mapped_path, _, histories = self.find()

        self.assertEqual(mapped_path, str(self.targets[0] / self.relative_path))
        self.assertEqual(histories, [matching])

    def test_same_strm_filename_in_two_destinations_remains_ambiguous(self):
        first = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[0] / self.relative_path).with_suffix(".mkv")),
        )
        third = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[2] / self.relative_path).with_suffix(".mkv")),
        )
        self.plugin._transferhis = TransferHistoryOper([first, third])

        mapped_path, _, histories = self.find()

        self.assertIsNone(mapped_path)
        self.assertEqual(histories, [])

    def test_single_mapping_selects_one_matching_filename(self):
        self.plugin._local_library_path = f"{self.source}#{self.targets[0]}"
        matching = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[0] / self.relative_path).with_suffix(".mkv")),
        )
        other = self.history_at(self.targets[0])
        self.plugin._transferhis = TransferHistoryOper([matching, other])

        mapped_path, _, histories = self.find()

        self.assertEqual(mapped_path, str(self.targets[0] / self.relative_path))
        self.assertEqual(histories, [matching])

    def test_exact_strm_history_has_priority_over_media_fallback(self):
        exact = TransferHistory(
            875828, MediaType.MOVIE.value,
            str(self.targets[0] / self.relative_path),
        )
        media = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[2] / self.relative_path).with_suffix(".mkv")),
        )
        self.plugin._transferhis = TransferHistoryOper([exact, media])

        mapped_path, _, histories = self.find()

        self.assertEqual(mapped_path, str(self.targets[0] / self.relative_path))
        self.assertEqual(histories, [exact])

    def test_ambiguous_first_destination_cannot_select_third(self):
        first = self.history_at(self.targets[0])
        another = TransferHistory(
            875828, MediaType.MOVIE.value,
            str((self.targets[0] / self.relative_path).with_name("other-version.mkv")),
        )
        third = self.history_at(self.targets[2])
        self.plugin._transferhis = TransferHistoryOper([first, another, third])

        mapped_path, _, histories = self.find()

        self.assertIsNone(mapped_path)
        self.assertEqual(histories, [])

    def test_existing_mapped_file_is_skipped(self):
        existing_path = self.targets[0] / self.relative_path
        existing_path.parent.mkdir(parents=True)
        existing_path.touch()
        expected = self.history_at(self.targets[2])
        self.plugin._transferhis = TransferHistoryOper(
            [self.history_at(self.targets[0]), expected]
        )

        mapped_path, _, histories = self.find()

        self.assertEqual(mapped_path, str(self.targets[2] / self.relative_path))
        self.assertEqual(histories, [expected])

    def test_whole_series_lookup_does_not_duplicate_path_independent_records(self):
        expected = TransferHistory(
            286506, MediaType.TV.value,
            str(self.targets[0] / self.series_relative_path / "Season 1/E01.mp4"),
        )
        self.plugin._transferhis = TransferHistoryOper([expected])

        mapped_path, _, histories = self.find(
            media_type="Series", media_path=self.series_emby_path, tmdb_id=286506
        )

        self.assertEqual(mapped_path, self.series_emby_path)
        self.assertEqual(histories, [expected])

    def test_whole_series_selects_all_mapped_records_with_existing_media_files(self):
        first_dest = self.targets[0] / self.series_relative_path / "Season 1/E04.mp4"
        second_dest = self.targets[1] / self.series_relative_path / "Season 1/E07.mkv"
        for dest in (first_dest, second_dest):
            dest.parent.mkdir(parents=True)
            dest.touch()
        first = TransferHistory(286506, MediaType.TV.value, str(first_dest))
        second = TransferHistory(286506, MediaType.TV.value, str(second_dest))
        unrelated = TransferHistory(
            286506, MediaType.TV.value,
            str(self.targets[2] / "电视剧/国产剧/其他剧/Season 1/E01.mkv"),
        )
        self.plugin._transferhis = TransferHistoryOper([first, second, unrelated])

        mapped_path, _, histories = self.find(
            media_type="Series", media_path=self.series_emby_path, tmdb_id=286506
        )

        self.assertEqual(mapped_path, self.series_emby_path)
        self.assertEqual(histories, [first, second])

    def test_whole_series_skips_when_emby_directory_still_exists(self):
        Path(self.series_emby_path).mkdir(parents=True)
        record = TransferHistory(
            286506, MediaType.TV.value,
            str(self.targets[0] / self.series_relative_path / "Season 1/E04.mp4"),
        )
        self.plugin._transferhis = TransferHistoryOper([record])

        mapped_path, _, histories = self.find(
            media_type="Series", media_path=self.series_emby_path, tmdb_id=286506
        )

        self.assertIsNone(mapped_path)
        self.assertEqual(histories, [])


if __name__ == "__main__":
    unittest.main()
