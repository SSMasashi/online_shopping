"""
テスト用フェイク（Google Sheets関連）。

tests/test_storage.py と tests/test_app.py の両方から使うため、
gspreadのSpreadsheet/Worksheet互換のフェイクをここにまとめる。
実際のGoogle Sheetsには一切接続しない。
"""

import gspread


class FakeWorksheet:
    """
    gspreadのWorksheetを模したフェイク。

    title と2次元リストの値を持ち、get_all_values / update / resize /
    row_count / col_count / clear を、実際のAPI通信なしに再現する。
    """

    def __init__(self, title, values=None, rows=100, cols=20, call_log=None, fail_on_update=False):
        self.title = title
        self.values = [list(row) for row in (values or [])]
        self._row_count = rows
        self._col_count = cols
        self.call_log = call_log
        self.fail_on_update = fail_on_update
        self.update_calls = []
        self.clear_calls = 0

    def get_all_values(self, **kwargs):
        return [list(row) for row in self.values]

    @property
    def row_count(self):
        return self._row_count

    @property
    def col_count(self):
        return self._col_count

    def resize(self, rows=None, cols=None):
        if rows is not None:
            self._row_count = rows
        if cols is not None:
            self._col_count = cols

    def update(self, values=None, range_name=None, value_input_option=None, **kwargs):
        if range_name not in (None, "A1"):
            raise AssertionError(f"range_nameはA1で呼ばれる想定です(実際: {range_name!r})")

        self.update_calls.append(
            {
                "values": [list(row) for row in values],
                "range_name": range_name,
                "value_input_option": value_input_option,
            }
        )

        if self.call_log is not None:
            self.call_log.append(self.title)

        if self.fail_on_update:
            raise RuntimeError(f"{self.title}のupdateに失敗しました（テスト用）")

        self.values = [list(row) for row in values]

        if len(self.values) > self._row_count:
            self._row_count = len(self.values)

        max_cols = max((len(row) for row in self.values), default=0)
        if max_cols > self._col_count:
            self._col_count = max_cols

    def clear(self):
        # 呼ばれたことだけ記録する。呼ばれていないことをテストで確認するため。
        self.clear_calls += 1


class FakeSpreadsheet:
    """
    gspreadのSpreadsheetを模したフェイク。

    title -> FakeWorksheet の辞書を持ち、worksheet / add_worksheet を再現する。
    全シート共通の call_log に update 呼び出し順（シート名）を記録するため、
    複数シートへの書き込み順序をテストできる。
    """

    def __init__(self, worksheets=None):
        self.call_log = []
        self.sheets = {}
        self.add_worksheet_calls = []

        for title, values in (worksheets or {}).items():
            self.sheets[title] = FakeWorksheet(title, values=values, call_log=self.call_log)

    def worksheet(self, title):
        if title not in self.sheets:
            raise gspread.WorksheetNotFound(title)

        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title, values=[], rows=rows, cols=cols, call_log=self.call_log)
        self.sheets[title] = ws
        self.add_worksheet_calls.append(title)
        return ws
