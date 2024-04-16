# projz_renpy_translation, a translator for RenPy games
# Copyright (C) 2023  github.com/abse4411
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import json
import os.path
from typing import Dict, List

import pandas as pd

from injection import Project
from store import TranslationIndex, index_type
from store.database.base import db_context
from store.index import extra_data_of
from store.index_type import register_index
from store.misc import ast_of, block_of
from util import default_read, default_write, strip_or_none, file_name, exists_file, assert_not_blank


class FileTranslationConvertor:
    def __init__(self, fn: str):
        self.fn = fn

    def get_text_map(self) -> Dict[str, str]:
        """
        Get all texts that need to translate as a map from self.fn.

        :return: List[str]
        """
        raise NotImplementedError()

    def save_to(self, fn: str, tran_map: Dict[str, str]):
        """
        Save translated texts into the given file.

        :param fn: Filename to save
        :param tran_map: A map of [raw text, new text]
        :return:
        """
        raise NotImplementedError()


class MToolConvertor(FileTranslationConvertor):
    def __init__(self, fn):
        super().__init__(fn)

    def get_text_map(self) -> Dict[str, str]:
        with default_read(self.fn) as f:
            data = json.load(f)
        texts = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                if k.strip() == '':
                    continue
                v = strip_or_none(v)
                texts[k] = v if k != v else None
        return texts

    def save_to(self, fn: str, tran_map: Dict[str, str]):
        with default_write(fn) as f:
            json.dump(tran_map, f, ensure_ascii=False, indent=4)


class XUnityConvertor(FileTranslationConvertor):
    def __init__(self, fn):
        super().__init__(fn)

    def get_text_map(self) -> Dict[str, str]:
        with default_read(self.fn) as f:
            data = f.readlines()
        texts = {}
        for t in data:
            if '=' in t:
                t = t.rstrip()
                pos = t.find('=')
                k = t[:pos]
                if k.strip() == '':
                    continue
                v = t[pos + 1:]
                v = strip_or_none(v)
                texts[k] = v if k != v else None
        return texts

    def save_to(self, fn: str, tran_map: Dict[str, str]):
        with default_write(fn) as f:
            for k, v in tran_map.items():
                v = v.replace('\n', '\\n').replace('\r', '\\r')
                f.write(f'{k}={v}\n')


class TranslatorPPConvertor(FileTranslationConvertor):
    def __init__(self, fn):
        super().__init__(fn)

    def get_text_map(self) -> Dict[str, str]:
        texts = {}
        df = pd.read_excel(self.fn, na_filter=False, usecols=[0, 1], header=None, skiprows=[0], dtype=str)
        for old_text, new_text in zip(df[0], df[1]):
            if old_text is None or old_text.strip() == '':
                continue
            new_text = strip_or_none(new_text)
            texts[old_text] = new_text if old_text != new_text else None
        return texts

    def save_to(self, fn: str, tran_map: Dict[str, str]):
        odata = []
        idata = []
        cols = ['Original Text', 'Initial', 'Machine translation', 'Better translation', 'Best translation']
        for k, v in tran_map.items():
            odata.append(k)
            idata.append(v)
        empty_arr = [None] * len(idata)
        df = pd.DataFrame({cols[0]: odata, cols[1]: idata, cols[2]: empty_arr, cols[3]: empty_arr})
        df = df.reindex(columns=cols)
        df.to_excel(fn, index=False)


_CONVERTORS = {
    'mt': (MToolConvertor, 'ManualTransFile.json generated by MTool.\n'
                           '---------------Example---------------\n'
                           '{\n'
                           '    "old text": "new_text",\n'
                           '    "hello world": "你好世界",\n'
                           '}\n'
                           '-------------------------------------'),
    'xu': (XUnityConvertor, '_AutoGeneratedTranslations.txt generated by XUnity Auto Translator.\n'
                            '---------------Example---------------\n'
                            'old_text=new_text\n'
                            'hello world=你好世界\n'
                            '-------------------------------------'),
    'tp': (TranslatorPPConvertor, 'xlsx/xls file generated by Translator++.\n'
                                  '---------------Example---------------\n'
                                  'Original Text|Initial|Machine translation|Better translation|Best translation\n'
                                  'old_text|new_text\n'
                                  'hello world|你好世界\n'
                                  '-------------------------------------')
}


def available_convertors():
    return list(_CONVERTORS.keys())


def convertors_info():
    res = []
    for k, v in _CONVERTORS.items():
        res.append([k, v[1]])
    return res


class FileTranslationIndex(TranslationIndex):

    def __init__(self, project: Project, nickname: str, tag: str, stats: dict = None, db_file: str = None,
                 extra_data: dict = None, doc_id: int = None):
        extra_data = extra_data_of(index_type.FILE, extra_data)
        super().__init__(project, nickname, tag, stats, db_file, extra_data, doc_id)

    @property
    def project_name(self):
        return self._project.project_name

    @property
    def project_version(self):
        return self.project.executable_path

    @classmethod
    def from_file(cls, file_path: str, file_type: str, nickname: str = None, tag: str = None):
        assert file_type in _CONVERTORS, f'Unknown file type: {file_type}'
        assert exists_file(file_path), f'{file_path} is not a file.'
        nickname, tag = cls._process_name(nickname, tag)
        nickname, tag = cls.check_existing_with(nickname, tag)
        filename = file_name(file_path)
        file_path = os.path.abspath(file_path)
        project = Project(file_path, file_type, filename)
        return cls(
            project=project,
            nickname=nickname,
            tag=tag
        )

    @classmethod
    def from_index(cls, index: TranslationIndex):
        if index.itype == index_type.FILE:
            res = cls(index.project, index.nickname, index.tag, index._stats, index._db_file, index._extra_data,
                      index.doc_id)
            return res
        else:
            raise ValueError(f'Unable to cast {index.to_dict()} into a FileTranslationIndex')

    @db_context
    def import_translations(self, lang: str, translated_only: bool = True, say_only: bool = True, **kwargs):
        lang = assert_not_blank(lang, 'lang')
        data = _CONVERTORS[self.project.executable_path][0](self.project_path).get_text_map()
        if data:
            with self._open_db() as dao:
                self.drop_translations(lang)
                dlang, slang = self._get_table_name(lang)
                string_data = []
                for k, v in data.items():
                    string_data.append(ast_of(language=lang, filename=self.project_path, linenumber=0, identifier=k,
                                              block=[block_of(type='String', what=k, code='', new_code=v)]))
                dao.add_batch(slang, string_data)
                # update statistics when updating translation
                self.update_translation_stats(lang, say_only=say_only)
        else:
            print(f'Empty translations of language {lang}')
        print(f'{lang}: 0 dialogue translations and {len(data)} string translations found')

    @db_context
    def export_translations(self, lang: str, translated_only: bool = True, say_only: bool = True, **kwargs):
        lang = assert_not_blank(lang, 'lang')
        if not self.exists_lang(lang):
            print(f'No {lang} translations to export')
            return
        _, string_data = self._list_translations(lang)
        new_string_data = {}
        for v in string_data:
            for i, b in enumerate(v['block']):
                if b['new_code'] is not None:
                    new_string_data[b['what']] = b['new_code']
                elif not translated_only:
                    new_string_data[b['what']] = b['what']
        if len(new_string_data) == 0:
            print(f'No {lang} translations in this TranslationIndex to export')
            return
        print(f'{lang}: 0 dialogue and {len(new_string_data)} string translations '
              f'are ready to export')
        name, ext = os.path.splitext(self.project_path)
        save_fn = name + f'_{lang}' + ext
        _CONVERTORS[self.project.executable_path][0](self.project_path).save_to(save_fn, new_string_data)
        print(f'We have written translations to: {save_fn}')

    def count_translations(self, lang: str, show_detail: bool = False, say_only: bool = True):
        raise NotImplementedError()


register_index(FileTranslationIndex.from_index, index_type.FILE)
