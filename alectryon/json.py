# Copyright © 2019 Clément Pit-Claudel
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import json
from os import path, makedirs
from itertools import zip_longest

from . import core

TYPE_OF_ALIASES = {
    "text": core.Text,
    "hypothesis": core.Hypothesis,
    "goal": core.Goal,
    "message": core.Message,
    "sentence": core.Sentence,
    "goals": core.Goals,
    "messages": core.Messages,
    "rich_sentence": core.RichSentence,
}

ALIASES_OF_TYPE = {
    cls.__name__: alias for (alias, cls) in TYPE_OF_ALIASES.items()
}

TYPES = list(TYPE_OF_ALIASES.values())

def json_of_annotated(obj):
    if isinstance(obj, list):
        return [json_of_annotated(x) for x in obj]
    if isinstance(obj, dict):
        return {k: json_of_annotated(v) for k, v in obj.items()}
    type_name = ALIASES_OF_TYPE.get(type(obj).__name__)
    if type_name:
        d = {"_type": type_name}
        for k, v in zip(obj._fields, obj):
            d[k] = json_of_annotated(v)
        return d
    assert obj is None or isinstance(obj, (int, str))
    return obj

def minimal_json_of_annotated(obj):
    if isinstance(obj, list):
        return [minimal_json_of_annotated(x) for x in obj]
    if isinstance(obj, dict):
        return {k: minimal_json_of_annotated(v) for k, v in obj.items()}
    type_name = ALIASES_OF_TYPE.get(type(obj).__name__)
    if type_name:
        if isinstance(obj, core.Text):
            return obj.contents
        d = {k: minimal_json_of_annotated(v) for k, v in zip(obj._fields, obj)}
        contents = d.pop("contents", None)
        d = {k: v for k, v in d.items() if v}
        if contents:
            d[type_name] = contents
        return d
    return obj

def annotated_of_json(js):
    if isinstance(js, list):
        return [annotated_of_json(x) for x in js]
    if isinstance(js, dict):
        type_name = js.get("_type")
        type_constr = TYPE_OF_ALIASES.get(type_name)
        obj = {k: annotated_of_json(v) for k, v in js.items()}
        if type_constr:
            del obj["_type"]
            return type_constr(**obj)
        return obj
    return js

def validate_inputs(annotated, reference):
    if isinstance(annotated, list):
        if not isinstance(reference, list):
            print(f"Mismatch: {annotated} {reference}")
            return False
        return all(validate_inputs(*p) for p in zip_longest(annotated, reference))
    # pylint: disable=isinstance-second-argument-not-valid-type
    if isinstance(annotated, TYPES):
        if annotated.contents != reference:
            print(f"Mismatch: {annotated.contents} {reference}")
        return annotated.contents == reference
    return False

def validate_metadata(metadata, reference, cache_file):
    if metadata != reference:
        MSG = "Outdated metadata in {} ({} != {})"
        print(MSG.format(cache_file, metadata, reference))
        return False
    return True

def validate_data(data, reference, cache_file):
    if data != reference:
        MSG = "Outdated contents in {}: recomputing"
        print(MSG.format(cache_file))
        return False
    return True

class Cache:
    def __init__(self, data, cache_file):
        self.data = data
        self.cache_file = cache_file

    @staticmethod
    def normalize(obj):
        if isinstance(obj, (list, tuple)):
            return [Cache.normalize(o) for o in obj]
        if isinstance(obj, dict):
            return {k: Cache.normalize(v) for (k, v) in obj.items()}
        return obj

    def _validate(self, chunks, metadata):
        return (self.data is not None
           and validate_metadata(self.data["metadata"], metadata, self.cache_file)
           and validate_data(self.data.get("chunks"), chunks, self.cache_file))

    def get(self, chunks, metadata):
        if not self._validate(self.normalize(chunks), self.normalize(metadata)):
            return None
        return annotated_of_json(self.data.get("annotated"))

    @property
    def generator(self):
        return self.data.get("generator", ["Coq+SerAPI", "??"])

    def put(self, chunks, metadata, annotated, generator):
        self.data = {"generator": generator,
                   "metadata": self.normalize(metadata),
                   "chunks": list(chunks),
                   "annotated": json_of_annotated(annotated)}

class FileCacheSet:
    CACHE_VERSION = "2"
    METADATA = {"cache_version": CACHE_VERSION}

    def __init__(self, cache_root, doc_path):
        self.cache_root = path.realpath(cache_root)
        doc_root = path.commonpath((self.cache_root, path.realpath(doc_path)))
        self.cache_rel_file = path.relpath(doc_path, doc_root) + ".cache"
        self.cache_file = path.join(cache_root, self.cache_rel_file)
        self.cache_dir = path.dirname(self.cache_file)
        makedirs(self.cache_dir, exist_ok=True)

        js = self._read()
        self.caches = {}
        if js and validate_metadata(js["metadata"], self.METADATA, self.cache_rel_file):
            for lang, data in js["caches"].items():
                self.caches[lang] = Cache(data, self.cache_rel_file)

    def __enter__(self):
        return self

    def __exit__(self, *_exn):
        self._write()
        return False

    def __getitem__(self, lang):
        if lang not in self.caches:
            self.caches[lang] = Cache(None, self.cache_rel_file)
        return self.caches[lang]

    def _read(self):
        try:
            with open(self.cache_file) as cache:
                return json.load(cache)
        except FileNotFoundError:
            return None

    def _write(self):
        with open(self.cache_file, mode="w") as cache:
            json.dump({ "metadata": self.METADATA,
                        "caches": { lang: c.data for (lang, c) in self.caches.items() } },
                      cache, indent=2)

class DummyCacheSet():
    def __init__(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exn):
        return False

    def __getitem__(self, lang):
        return Cache(None, None)

def CacheSet(cache_root, doc_path):
    return (FileCacheSet if cache_root is not None else DummyCacheSet)(cache_root, doc_path)
