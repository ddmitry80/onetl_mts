import logging
import os
import pytest
import tempfile
from pathlib import Path, PosixPath

from onetl.connection.file_connection import HDFS
from onetl.downloader import FileDownloader
from onetl.uploader import FileUploader
from tests.lib.common import hashfile


class TestHDFS:
    def test_hdfs_source_check(self, caplog):
        hdfs = HDFS(host="hive2", port=50070)

        with caplog.at_level(logging.INFO):
            hdfs.check()
        assert "Connection is available" in caplog.text

    def test_hdfs_wrong_source_check(self):
        hdfs = HDFS(host="hive1", port=1234)

        with pytest.raises(RuntimeError):
            hdfs.check()

    def test_hdfs_file_uploader_with_empty_file_list(self, caplog):
        hdfs = HDFS(host="hive2", port=50070)
        uploader = FileUploader(connection=hdfs, target_path="/target/path/")
        with caplog.at_level(logging.INFO):
            uploaded_files = uploader.run([])
            assert "Files list is empty. Please, provide files to upload." in caplog.text
        assert not uploaded_files

    def test_hdfs_file_uploader(self, test_file_path, test_file_name):
        hdfs = HDFS(host="hive2", port=50070)
        uploader = FileUploader(connection=hdfs, target_path="/user/onetl/test_upload")

        files = [
            test_file_path,
        ]

        uploaded_files = uploader.run(files)
        assert uploaded_files == [PosixPath("/user/onetl/test_upload") / test_file_name]
        hdfs.rmdir("/user/onetl/test_upload", True)

    def test_hdfs_file_downloader(self, test_file_path, test_file_name):
        hdfs = HDFS(host="hive2", port=50070)
        hdfs.client.upload(
            Path("/user/onetl/test_download") / test_file_name,
            test_file_path,
        )

        with tempfile.TemporaryDirectory() as local_path:

            downloader = FileDownloader(
                connection=hdfs,
                source_path="/user/onetl/test_download",
                local_path=local_path,
            )

            downloaded_files = downloader.run()

            # file list comparison
            assert downloaded_files == [PosixPath(local_path) / test_file_name]
            # compare size of files
            assert os.path.getsize(test_file_path) == os.path.getsize(Path(local_path) / test_file_name)
            # compare files
            assert hashfile(test_file_path) == hashfile(Path(local_path) / test_file_name)
            hdfs.rmdir(Path("/user/onetl/test_download"), True)

    def test_hdfs_file_downloader_with_delete_source(self, test_file_path, test_file_name):
        hdfs = HDFS(host="hive2", port=50070)
        hdfs.client.upload(
            Path("/user/onetl/test_delete_source") / test_file_name,
            test_file_path,
        )

        with tempfile.TemporaryDirectory() as local_path:

            downloader = FileDownloader(
                connection=hdfs,
                source_path="/user/onetl/test_delete_source",
                local_path=local_path,
                delete_source=True,
            )

            downloaded_files = downloader.run()

            assert downloaded_files == [PosixPath(local_path) / test_file_name]
            assert not hdfs.path_exists(Path("/user/onetl/test_delete_source") / test_file_name)
