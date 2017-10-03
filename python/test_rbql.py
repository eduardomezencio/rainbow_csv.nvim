#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import print_function

import sys
import os
import argparse
import random
import unittest
import re
import tempfile
import time
import importlib
import codecs
import io
import rbql
import subprocess
import rbql_utils

#This module must be both python2 and python3 compatible


default_csv_encoding = rbql.default_csv_encoding

TEST_JS = True

def table_to_string(array2d, delim):
    result = '\n'.join([delim.join(ln) for ln in array2d])
    if len(array2d):
        result += '\n'
    return result


def table_to_file(array2d, dst_path, delim='\t'):
    with codecs.open(dst_path, 'w', 'latin-1') as f:
        for row in array2d:
            f.write(delim.join(row))
            f.write('\n')


def table_to_stream(array2d, delim):
    return io.StringIO(table_to_string(array2d, delim))


rainbow_ut_prefix = 'ut_rbconvert_'


def run_file_query_test_py(query, input_path, testname, import_modules=None, csv_encoding=default_csv_encoding, delim='\t'):
    tmp_dir = tempfile.gettempdir()
    if not len(sys.path) or sys.path[0] != tmp_dir:
        sys.path.insert(0, tmp_dir)
    module_name = '{}{}_{}_{}'.format(rainbow_ut_prefix, time.time(), testname, random.randint(1, 100000000)).replace('.', '_')
    module_filename = '{}.py'.format(module_name)
    tmp_path = os.path.join(tmp_dir, module_filename)
    dst_table_filename = '{}.tsv'.format(module_name)
    output_path = os.path.join(tmp_dir, dst_table_filename)
    rbql.parse_to_py([query], tmp_path, delim, csv_encoding, import_modules)
    rbconvert = rbql.dynamic_import(module_name)
    warnings = None
    with codecs.open(input_path, encoding=csv_encoding) as src, codecs.open(output_path, 'w', encoding=csv_encoding) as dst:
        warnings = rbconvert.rb_transform(src, dst)
    assert os.path.exists(tmp_path)
    rbql.remove_if_possible(tmp_path)
    assert not os.path.exists(tmp_path)
    return (output_path, warnings)


def run_conversion_test_py(query, input_table, testname, import_modules=None, join_csv_encoding=default_csv_encoding, delim='\t'):
    tmp_dir = tempfile.gettempdir()
    if not len(sys.path) or sys.path[0] != tmp_dir:
        sys.path.insert(0, tmp_dir)
    module_name = '{}{}_{}_{}'.format(rainbow_ut_prefix, time.time(), testname, random.randint(1, 100000000)).replace('.', '_')
    module_filename = '{}.py'.format(module_name)
    tmp_path = os.path.join(tmp_dir, module_filename)
    #print( "tmp_path:", tmp_path) #FOR_DEBUG
    src = table_to_stream(input_table, delim)
    dst = io.StringIO()
    rbql.parse_to_py([query], tmp_path, delim, join_csv_encoding, import_modules)
    assert os.path.isfile(tmp_path) and os.access(tmp_path, os.R_OK)
    rbconvert = rbql.dynamic_import(module_name)
    warnings = rbconvert.rb_transform(src, dst)
    out_data = dst.getvalue()
    if len(out_data):
        out_lines = out_data[:-1].split('\n')
        out_table = [ln.split('\t') for ln in out_lines]
    else:
        out_table = []
    assert os.path.exists(tmp_path)
    rbql.remove_if_possible(tmp_path)
    assert not os.path.exists(tmp_path)
    return (out_table, warnings)


def run_file_query_test_js(query, input_path, testname, import_modules=None, csv_encoding=default_csv_encoding, delim='\t'):
    tmp_dir = tempfile.gettempdir()
    rnd_string = '{}{}_{}_{}'.format(rainbow_ut_prefix, time.time(), testname, random.randint(1, 100000000)).replace('.', '_')
    script_filename = '{}.js'.format(rnd_string)
    tmp_path = os.path.join(tmp_dir, script_filename)
    dst_table_filename = '{}.tsv'.format(rnd_string)
    output_path = os.path.join(tmp_dir, dst_table_filename)
    rbql.parse_to_js(input_path, output_path, [query], tmp_path, delim, csv_encoding, import_modules)
    cmd = ['node', tmp_path]
    pobj = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_data, err_data = pobj.communicate()
    exit_code = pobj.returncode

    operation_report = rbql.parse_json_report(exit_code, err_data)
    warnings = operation_report.get('warnings')
    operation_error = operation_report.get('error')
    if operation_error is not None:
        raise RuntimeError("Error in file test: {}.\nError text:\n{}\n\nScript location: {}".format(testname, operation_error, tmp_path))

    assert os.path.exists(tmp_path)
    rbql.remove_if_possible(tmp_path)
    assert not os.path.exists(tmp_path)
    return (output_path, warnings)


def run_conversion_test_js(query, input_table, testname, import_modules=None, csv_encoding=default_csv_encoding, delim='\t'):
    tmp_dir = tempfile.gettempdir()
    script_name = '{}{}_{}_{}'.format(rainbow_ut_prefix, time.time(), testname, random.randint(1, 100000000)).replace('.', '_')
    script_name += '.js'
    tmp_path = os.path.join(tmp_dir, script_name)
    rbql.parse_to_js(None, None, [query], tmp_path, delim, csv_encoding, None)
    src = table_to_string(input_table, delim)
    cmd = ['node', tmp_path]
    pobj = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    out_data, err_data = pobj.communicate(src.encode(csv_encoding))
    exit_code = pobj.returncode

    operation_report = rbql.parse_json_report(exit_code, err_data)
    warnings = operation_report.get('warnings')
    operation_error = operation_report.get('error')
    if operation_error is not None:
        raise RuntimeError("Error in file test: {}.\nError text:\n{}\n\nScript location: {}".format(testname, operation_error, tmp_path))

    out_table = []
    out_data = out_data.decode(csv_encoding)
    if len(out_data):
        out_lines = out_data[:-1].split('\n')
        out_table = [ln.split('\t') for ln in out_lines]
    assert os.path.exists(tmp_path)
    rbql.remove_if_possible(tmp_path)
    assert not os.path.exists(tmp_path)
    return (out_table, warnings)


def make_random_csv_entry(min_len, max_len, restricted_chars):
    strlen = random.randint(min_len, max_len)
    char_set = list(range(256))
    restricted_chars = [ord(c) for c in restricted_chars]
    char_set = [c for c in char_set if c not in restricted_chars]
    data = list()
    for i in rbql.xrange6(strlen):
        data.append(random.choice(char_set))
    pseudo_latin = bytes(bytearray(data)).decode('latin-1')
    return pseudo_latin


def stochastic_escape(src):
    assert src.find('"') == -1
    if src.find(',') == -1 and random.randint(0, 10) > 2:
        return src
    return '"{}"'.format(src)


def generate_random_scenario(max_num_rows, max_num_cols, delims):
    num_rows = random.randint(1, max_num_rows)
    num_cols = random.randint(1, max_num_cols)
    delim = random.choice(delims)
    restricted_chars = ['\r', '\n', '\t']
    if delim == ',':
        restricted_chars.append('"')
    if delim == ';':
        restricted_chars.append(';')
    key_col = random.randint(0, num_cols - 1)
    good_keys = ['Hello', 'Avada, Keda,vra ', ' ??????', '128', '3q295 fa,#(@*$*)', ' abc,defg ', 'NR', 'a1', 'a2']
    input_table = list()
    for r in rbql.xrange6(num_rows):
        input_table.append(list())
        for c in rbql.xrange6(num_cols):
            if c != key_col:
                input_table[-1].append(make_random_csv_entry(0, 20, restricted_chars))
            else:
                input_table[-1].append(random.choice(good_keys))

    canonic_table = list()
    target_key = random.choice(good_keys)
    if random.choice([True, False]):
        sql_op = '!='
        canonic_table = [row[:] for row in input_table if row[key_col] != target_key]
    else:
        sql_op = '=='
        canonic_table = [row[:] for row in input_table if row[key_col] == target_key]
    query = 'select * where a{} {} "{}"'.format(key_col + 1, sql_op, target_key)

    if delim == ',':
        for r in range(len(input_table)):
            for c in range(len(input_table[r])):
                input_table[r][c] = stochastic_escape(input_table[r][c])

    return (input_table, query, canonic_table, delim)



def compare_warnings(tester, canonic_warnings, test_warnings):
    if test_warnings is None:
        tester.assertTrue(canonic_warnings is None)
        return
    if canonic_warnings is None:
        canonic_warnings = list()
    canonic_warnings = sorted(canonic_warnings)
    test_warnings = sorted(test_warnings.keys())
    tester.assertEqual(canonic_warnings, test_warnings)


class TestEverything(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tmp_dir = tempfile.gettempdir()
        old_unused = [f for f in os.listdir(tmp_dir) if f.startswith(rainbow_ut_prefix)]
        for name in old_unused:
            script_path = os.path.join(tmp_dir, name)
            os.remove(script_path)


    def compare_tables(self, canonic_table, test_table):
        self.assertEqual(len(canonic_table), len(test_table))
        for i in rbql.xrange6(len(canonic_table)):
            self.assertEqual(len(canonic_table[i]), len(test_table[i]))
            self.assertEqual(canonic_table[i], test_table[i])
        self.assertEqual(canonic_table, test_table)


    def test_random_bin_tables(self):
        test_name = 'test_random_bin_tables'
        for subtest in rbql.xrange6(20):
            input_table, query, canonic_table, delim = generate_random_scenario(200, 6, ['\t', ',', ';'])

            test_table, warnings = run_conversion_test_py(query, input_table, test_name, delim=delim)
            self.compare_tables(canonic_table, test_table)

            if TEST_JS:
                test_table, warnings = run_conversion_test_js(query, input_table, test_name, delim=delim)
                self.compare_tables(canonic_table, test_table)


    def test_run1(self):
        test_name = 'test1'

        input_table = list()
        input_table.append(['5', 'haha', 'hoho'])
        input_table.append(['-20', 'haha', 'hioho'])
        input_table.append(['50', 'haha', 'dfdf'])
        input_table.append(['20', 'haha', ''])

        canonic_table = list()
        canonic_table.append(['3', '50', '4'])
        canonic_table.append(['4', '20', '0'])

        query = 'select NR, a1, len(a3) where int(a1) > 5'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = 'select NR, a1, a3.length where a1 > 5'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run2(self):
        test_name = 'test2'

        input_table = list()
        input_table.append(['5', 'haha', 'hoho'])
        input_table.append(['-20', 'haha', 'hioho'])
        input_table.append(['50', 'haha', 'dfdf'])
        input_table.append(['20', 'haha', ''])
        input_table.append(['8'])
        input_table.append(['3', '4', '1000', 'asdfasf', 'asdfsaf', 'asdfa'])
        input_table.append(['11', 'hoho', ''])
        input_table.append(['10', 'hihi', ''])
        input_table.append(['13', 'haha', ''])

        canonic_table = list()
        canonic_table.append(['haha'])
        canonic_table.append(['hoho'])

        query = '\tselect    distinct\ta2 where int(a1) > 10 '
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, ['input_fields_info'], warnings)

        if TEST_JS:
            query = '\tselect    distinct\ta2 where a1 > 10  '
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, ['input_fields_info'], warnings)


    def test_run4(self):
        test_name = 'test4'
        input_table = list()
        input_table.append(['0', 'haha', 'hoho'])
        input_table.append(['9'])
        input_table.append(['81', 'haha', 'dfdf'])
        input_table.append(['4', 'haha', 'dfdf', 'asdfa', '111'])

        canonic_table = list()
        canonic_table.append(['0', r"\'\"a1   bc"])
        canonic_table.append(['3', r"\'\"a1   bc"])
        canonic_table.append(['9', r"\'\"a1   bc"])
        canonic_table.append(['2', r"\'\"a1   bc"])

        query = r'select int(math.sqrt(int(a1))), r"\'\"a1   bc"'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name, ['math', 'os'])
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, ['input_fields_info'], warnings)

        if TEST_JS:
            query = r'select Math.floor(Math.sqrt(a1)), String.raw`\'\"a1   bc`'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, ['input_fields_info'], warnings)


    #TODO add test with js regex with multiple spaces and check that it is preserved during parsing

    def test_run5(self):
        test_name = 'test5'
        query = 'select a2'
        input_table = list()
        input_table.append(['0', 'haha', 'hoho'])
        input_table.append(['9'])
        input_table.append(['81', 'haha', 'dfdf'])
        input_table.append(['4', 'haha', 'dfdf', 'asdfa', '111'])

        with self.assertRaises(Exception) as cm:
            run_conversion_test_py(query, input_table, test_name, ['math', 'os'])
        e = cm.exception
        self.assertTrue(str(e).find('No "a2" column at line: 2') != -1)

        if TEST_JS:
            with self.assertRaises(Exception) as cm:
                run_conversion_test_js(query, input_table, test_name)
            e = cm.exception
            self.assertTrue(str(e).find('No "a2" column at line: 2') != -1)


    def test_run6(self):
        test_name = 'test6'

        input_table = list()
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'Ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['20', 'boat', 'destroyer\r'])
        input_table.append(['10', 'boat', 'yacht '])
        input_table.append(['200', 'plane', 'boeing 737'])
        input_table.append(['80', 'train', 'Thomas'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas '])
        join_table.append(['plane', 'wings  \r'])
        join_table.append(['boat', 'wind\r'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        canonic_table = list()
        canonic_table.append(['5', '10', 'boat', 'yacht ', 'boat', 'wind'])
        canonic_table.append(['4', '20', 'boat', 'destroyer', 'boat', 'wind'])
        canonic_table.append(['2', '-20', 'car', 'Ferrari', 'car', 'gas '])
        canonic_table.append(['1', '5', 'car', 'lada', 'car', 'gas '])
        canonic_table.append(['3', '50', 'plane', 'tu-134', 'plane', 'wings  '])
        canonic_table.append(['6', '200', 'plane', 'boeing 737', 'plane', 'wings  '])

        query = r'select NR, * inner join {} on a2 == b1 where b2 != "haha" and int(a1) > -100 and len(b2) > 1 order by a2, int(a1)'.format(join_table_path)
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None,  warnings)

        if TEST_JS:
            query = r'select NR, * inner join {} on a2 == b1 where   b2 !=  "haha" &&  a1 > -100 &&  b2.length >  1 order by a2, parseInt(a1)'.format(join_table_path)
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run7(self):
        test_name = 'test7'

        input_table = list()
        input_table.append(['100', 'magic carpet', 'nimbus 3000'])
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['20', 'boat', 'destroyer'])
        input_table.append(['10', 'boat', 'yacht'])
        input_table.append(['200', 'plane', 'boeing 737'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas'])
        join_table.append(['plane', 'wings'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        canonic_table = list()
        canonic_table.append(['', '', '100'])
        canonic_table.append(['car', 'gas', '5'])
        canonic_table.append(['car', 'gas', '-20'])
        canonic_table.append(['', '', '20'])
        canonic_table.append(['', '', '10'])

        query = r'select b1,b2,   a1 left join {} on a2 == b1 where b2 != "wings"'.format(join_table_path)
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, ['null_value_in_output'], warnings)

        if TEST_JS:
            query = r'select b1,b2,   a1 left join {} on a2 == b1 where b2 != "wings"'.format(join_table_path)
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, ['null_value_in_output'], warnings)


    def test_run8(self):
        test_name = 'test8'

        input_table = list()
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['20', 'boat', 'destroyer'])
        input_table.append(['10', 'boat', 'yacht'])
        input_table.append(['200', 'plane', 'boeing 737'])
        input_table.append(['100', 'magic carpet', 'nimbus 3000'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas'])
        join_table.append(['plane', 'wings'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        query = r'select b1,b2,   a1 strict left join {} on a2 == b1 where b2 != "wings"'.format(join_table_path)
        with self.assertRaises(Exception) as cm:
            test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        e = cm.exception
        self.assertTrue(str(e).find('all A table keys must be present in table B') != -1)

        if TEST_JS:
            query = r'select b1,b2,   a1 strict left join {} on a2 == b1 where b2 != "wings"'.format(join_table_path)
            with self.assertRaises(Exception) as cm:
                test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            e = cm.exception
            self.assertTrue(str(e).find('all A table keys must be present in table B') != -1)


    def test_run9(self):
        test_name = 'test9'

        input_table = list()
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['200', 'plane', 'boeing 737'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas'])
        join_table.append(['plane', 'wings'])
        join_table.append(['plane', 'air'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        query = r'select b1,b2,a1 inner join {} on a2 == b1 where b1 != "car"'.format(join_table_path)
        with self.assertRaises(Exception) as cm:
            test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        e = cm.exception
        self.assertTrue(str(e).find('Join column must be unique in right-hand-side "B" table') != -1)

        if TEST_JS:
            query = r'select b1,b2,a1 inner join {} on a2 == b1 where b1 != "car"'.format(join_table_path)
            with self.assertRaises(Exception) as cm:
                test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            e = cm.exception
            self.assertTrue(str(e).find('Join column must be unique in right-hand-side "B" table') != -1)


    def test_run10(self):
        test_name = 'test10'

        input_table = list()
        input_table.append(['5', 'haha', 'hoho'])
        input_table.append(['-20', 'haha', 'hioho'])
        input_table.append(['50', 'haha', 'dfdf'])
        input_table.append(['20', 'haha', ''])

        canonic_table = list()
        canonic_table.append(['5', 'haha', 'hoho'])
        canonic_table.append(['50', 'haha', 'dfdf'])

        query = 'select * where a3 =="hoho" or int(a1)==50 or a1 == "aaaa" or a2== "bbbbb" '
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = 'select * where a3 =="hoho" || parseInt(a1)==50 || a1 == "aaaa" || a2== "bbbbb" '
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run11(self):
        test_name = 'test11'

        input_table = list()
        input_table.append(['5', 'Петр Первый', 'hoho'])
        input_table.append(['-20', 'Екатерина Великая', 'hioho\r'])
        input_table.append(['50', 'Наполеон', 'dfdf\r'])
        input_table.append(['20', 'Наполеон', '\r'])

        canonic_table = list()
        canonic_table.append(['50', 'Наполеон', 'dfdf'])
        canonic_table.append(['20', 'Наполеон', ''])

        query = 'select * where a2== "Наполеон" '
        test_table, warnings = run_conversion_test_py(query, input_table, test_name, join_csv_encoding='utf-8')
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = 'select * where a2== "Наполеон" '
            test_table, warnings = run_conversion_test_js(query, input_table, test_name, csv_encoding='utf-8')
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run12(self):
        test_name = 'test12'

        input_table = list()
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'Ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['20', 'boat', 'destroyer'])
        input_table.append(['10', 'boat', 'yacht'])
        input_table.append(['200', 'plane', 'boeing 737'])
        input_table.append(['80', 'train', 'Thomas'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas'])
        join_table.append(['plane', 'wings'])
        join_table.append(['boat', 'wind'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        canonic_table = list()
        canonic_table.append(['5', '10', 'boat', 'yacht', 'boat', 'wind'])
        canonic_table.append(['4', '20', 'boat', 'destroyer', 'boat', 'wind'])
        canonic_table.append(['2', '-20', 'car', 'Ferrari', 'car', 'gas'])
        canonic_table.append(['1', '5', 'car', 'lada', 'car', 'gas'])
        canonic_table.append(['3', '50', 'plane', 'tu-134', 'plane', 'wings'])
        canonic_table.append(['6', '200', 'plane', 'boeing 737', 'plane', 'wings'])

        query = r'select NR, * JOIN {} on a2 == b1 where b2 != "haha" and int(a1) > -100 and len(b2) > 1 order   by a2, int(a1)'.format(join_table_path)
        test_table, warnings= run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'select NR, * JOIN {} on a2 == b1 where b2 != "haha" && a1 > -100 && b2.length > 1 order    by a2, parseInt(a1)'.format(join_table_path)
            test_table, warnings= run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run13(self):
        test_name = 'test13'

        input_table = list()
        input_table.append(['5', 'haha   asdf', 'hoho'])
        input_table.append(['50', 'haha  asdf', 'dfdf'])
        input_table.append(['20', 'haha    asdf', ''])
        input_table.append(['-20', 'haha   asdf', 'hioho'])

        canonic_table = list()
        canonic_table.append(['5', 'haha   asdf', 'hoho'])
        canonic_table.append(['-20', 'haha   asdf', 'hioho'])

        query = r'select * where re.search("a   as", a2)  is   not  None'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'select * where /a   as/.test(a2)'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run14(self):
        test_name = 'test14'

        input_table = list()
        input_table.append(['5', 'haha   asdf', 'hoho'])
        input_table.append(['50', 'haha  asdf', 'dfdf'])
        input_table.append(['20', 'haha    asdf', ''])
        input_table.append(['-20', 'haha   asdf', 'hioho'])

        canonic_table = list()
        canonic_table.append(['5', 'haha   asdf', 'hoho'])
        canonic_table.append(['100', 'haha  asdf hoho', 'dfdf'])
        canonic_table.append(['100', 'haha    asdf hoho', ''])
        canonic_table.append(['-20', 'haha   asdf', 'hioho'])

        query = r'update a2 = a2 + " hoho", a1 = 100 where int(a1) > 10'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'update a2 = a2 + " hoho", a1 = 100 where parseInt(a1) > 10'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run15(self):
        test_name = 'test15'

        input_table = list()
        input_table.append(['5', 'Петр Первый', 'hoho'])
        input_table.append(['-20', 'Екатерина Великая', 'hioho\r'])
        input_table.append(['50', 'Наполеон', 'dfdf\r'])
        input_table.append(['20', 'Наполеон'])

        canonic_table = list()
        canonic_table.append(['5', 'Наполеон', 'hoho'])
        canonic_table.append(['-20', 'Наполеон', 'hioho'])
        canonic_table.append(['50', 'Наполеон', 'dfdf'])
        canonic_table.append(['20', 'Наполеон'])

        query = 'update set a2= "Наполеон" '
        test_table, warnings = run_conversion_test_py(query, input_table, test_name, join_csv_encoding='utf-8')
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, ['output_fields_info', 'input_fields_info'], warnings)

        if TEST_JS:
            query = 'update  set  a2= "Наполеон" '
            test_table, warnings = run_conversion_test_js(query, input_table, test_name, csv_encoding='utf-8')
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, ['output_fields_info', 'input_fields_info'], warnings)


    def test_run16(self):
        test_name = 'test16'

        input_table = list()
        input_table.append(['100', 'magic carpet', 'nimbus 3000'])
        input_table.append(['5', 'car', 'lada'])
        input_table.append(['-20', 'car', 'ferrari'])
        input_table.append(['50', 'plane', 'tu-134'])
        input_table.append(['20', 'boat', 'destroyer'])
        input_table.append(['10', 'boat', 'yacht'])
        input_table.append(['200', 'plane', 'boeing 737'])

        join_table = list()
        join_table.append(['bicycle', 'legs'])
        join_table.append(['car', 'gas'])
        join_table.append(['plane', 'wings'])
        join_table.append(['rocket', 'some stuff'])

        join_table_path = os.path.join(tempfile.gettempdir(), '{}_rhs_join_table.tsv'.format(test_name))
        table_to_file(join_table, join_table_path)

        canonic_table = list()
        canonic_table.append(['100', 'magic carpet', 'nimbus 3000'])
        canonic_table.append(['5', 'car (gas)', 'lada'])
        canonic_table.append(['-20', 'car (gas)', 'ferrari'])
        canonic_table.append(['50', 'plane', 'tu-134'])
        canonic_table.append(['20', 'boat', 'destroyer'])
        canonic_table.append(['10', 'boat', 'yacht'])
        canonic_table.append(['200', 'plane', 'boeing 737'])

        query = r'update set a2 = "{} ({})".format(a2, b2) inner join ' + join_table_path + ' on a2 == b1 where b2 != "wings"'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'update set a2 = a2 + " (" + b2 + ")" inner join ' + join_table_path + ' on a2 == b1 where b2 != "wings"'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run17(self):
        test_name = 'test17'

        input_table = list()
        input_table.append(['cde', '1234'])
        input_table.append(['abc', '1234'])
        input_table.append(['abc', '1234'])
        input_table.append(['efg', '100'])
        input_table.append(['abc', '100'])
        input_table.append(['cde', '12999'])
        input_table.append(['aaa', '2000'])
        input_table.append(['abc', '100'])

        canonic_table = list()
        canonic_table.append(['2', 'cde'])
        canonic_table.append(['4', 'abc'])
        canonic_table.append(['1', 'efg'])
        canonic_table.append(['1', 'aaa'])

        query = r'select distinct count a1 where int(a2) > 10'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'select distinct count a1 where parseInt(a2) > 10'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


    def test_run18(self):
        test_name = 'test18'

        input_table = list()
        input_table.append(['cde', '1234'])
        input_table.append(['abc', '1234'])
        input_table.append(['abc', '1234'])
        input_table.append(['efg', '100'])
        input_table.append(['abc', '100'])
        input_table.append(['cde', '12999'])
        input_table.append(['aaa', '2000'])
        input_table.append(['abc', '100'])

        canonic_table = list()
        canonic_table.append(['1', 'efg'])
        canonic_table.append(['4', 'abc'])

        query = r'select top 2 distinct count a1 where int(a2) > 10 order by int(a2) asc'
        test_table, warnings = run_conversion_test_py(query, input_table, test_name)
        self.compare_tables(canonic_table, test_table)
        compare_warnings(self, None, warnings)

        if TEST_JS:
            query = r'select top 2 distinct count a1 where parseInt(a2) > 10 order by parseInt(a2) asc'
            test_table, warnings = run_conversion_test_js(query, input_table, test_name)
            self.compare_tables(canonic_table, test_table)
            compare_warnings(self, None, warnings)


def calc_file_md5(fname):
    import hashlib
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


class TestFiles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.old_dir = os.getcwd()
        script_dir = os.path.dirname(os.path.realpath(__file__))
        ut_dir = os.path.join(script_dir, 'unit_tests')
        os.chdir(ut_dir)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.old_dir)

    def test_all(self):
        import json
        ut_config_path = 'unit_tests.cfg'
        has_node = rbql.system_has_node_js()
        if not has_node:
            rbql.eprint('unable to run js tests: Node.js is not found')
        with codecs.open(ut_config_path, encoding='utf-8') as src:
            for test_no, line in enumerate(src, 1):
                config = json.loads(line)
                src_path = config['src_table']
                canonic_table = config.get('canonic_table')
                canonic_error_msg = config.get('canonic_error_msg')
                canonic_warnings = config.get('warnings')
                if canonic_warnings is not None:
                    canonic_warnings = canonic_warnings.split(',')
                query = config['query']
                encoding = config.get('encoding', default_csv_encoding)
                delim = config.get('delim', 'TAB')
                if delim == 'TAB':
                    delim = '\t'
                meta_language = config.get('meta_language', 'python')
                canonic_path = None if canonic_table is None else os.path.abspath(canonic_table)
                canonic_md5 = calc_file_md5(canonic_table)

                if meta_language == 'python':
                    warnings = None
                    try:
                        result_table, warnings = run_file_query_test_py(query, src_path, str(test_no), csv_encoding=encoding, delim=delim)
                    except Exception as e:
                        if canonic_error_msg is None or str(e).find(canonic_error_msg) == -1:
                            raise
                        continue
                    test_path = os.path.abspath(result_table) 
                    test_md5 = calc_file_md5(result_table)
                    self.assertEqual(test_md5, canonic_md5, msg='Tables missmatch. Canonic: {}; Actual: {}'.format(canonic_path, test_path))
                    compare_warnings(self, canonic_warnings, warnings)
                
                elif TEST_JS:
                    assert meta_language == 'js'
                    if not has_node:
                        continue
                    try:
                        result_table, warnings = run_file_query_test_js(query, src_path, str(test_no), csv_encoding=encoding, delim=delim)
                    except Exception as e:
                        if canonic_error_msg is None or str(e).find(canonic_error_msg) == -1:
                            raise
                        continue
                    test_path = os.path.abspath(result_table) 
                    test_md5 = calc_file_md5(result_table)
                    self.assertEqual(test_md5, canonic_md5, msg='Tables missmatch. Canonic: {}; Actual: {}'.format(canonic_path, test_path))
                    compare_warnings(self, canonic_warnings, warnings)



class TestStringMethods(unittest.TestCase):
    def test_strip4(self):
        a = ''' # a comment  '''
        a_strp = rbql.strip_py_comments(a)
        self.assertEqual(a_strp, '')

    def test_strip5(self):
        a = ''' // a comment  '''
        a_strp = rbql.strip_js_comments(a)
        self.assertEqual(a_strp, '')


def natural_random(low, high):
    if low <= 0 and high >= 0 and random.randint(0, 2) == 0:
        return 0
    k = random.randint(0, 8)
    if k < 2:
        return low + k
    if k > 6:
        return high - 8 + k
    return random.randint(low, high)


def make_random_csv_fields(num_fields, max_field_len):
    available = [',', '"', 'a', 'b', 'c', 'd']
    result = list()
    for fn in range(num_fields):
        flen = natural_random(0, max_field_len)
        chosen = list()
        for i in range(flen):
            chosen.append(random.choice(available))
        result.append(''.join(chosen))
    return result


def randomly_csv_escape(fields):
    efields = list()
    for field in fields:
        escaped = field.replace('"', '""')
        if escaped.find('"') != -1 or escaped.find(',') != -1 or random.randint(0, 1) == 1:
            escaped = '"{}"'.format(escaped)
        efields.append(escaped)
    return ','.join(efields)


def make_random_csv_records():
    result = list()
    for num_test in rbql.xrange6(1000):
        num_fields = random.randint(1, 11)
        max_field_len = 25
        fields = make_random_csv_fields(num_fields, max_field_len)
        csv_line = randomly_csv_escape(fields)
        defective_escaping = random.randint(0, 1)
        if defective_escaping:
            defect_pos = random.randint(0, len(csv_line))
            csv_line = csv_line[:defect_pos] + '"' + csv_line[defect_pos:]
        result.append((fields, csv_line, defective_escaping))
    return result


class TestSplitMethods(unittest.TestCase):

    def test_split(self):
        test_cases = list()
        test_cases.append(('hello,world', (['hello','world'], False)))
        test_cases.append(('hello,"world"', (['hello','world'], False)))
        test_cases.append(('"abc"', (['abc'], False)))
        test_cases.append(('abc', (['abc'], False)))
        test_cases.append(('', ([''], False)))
        test_cases.append((',', (['',''], False)))
        test_cases.append((',,,', (['','','',''], False)))
        test_cases.append((',"",,,', (['','','','',''], False)))
        test_cases.append(('"","",,,""', (['','','','',''], False)))
        test_cases.append(('"aaa,bbb",', (['aaa,bbb',''], False)))
        test_cases.append(('"aaa,bbb",ccc', (['aaa,bbb','ccc'], False)))
        test_cases.append(('"aaa,bbb","ccc"', (['aaa,bbb','ccc'], False)))
        test_cases.append(('"aaa,bbb","ccc,ddd"', (['aaa,bbb','ccc,ddd'], False)))
        test_cases.append(('"aaa,bbb",ccc,ddd', (['aaa,bbb','ccc', 'ddd'], False)))
        test_cases.append(('"a"aa" a,bbb",ccc,ddd', (['a"aa" a,bbb','ccc', 'ddd'], True)))
        test_cases.append(('"aa, bb, cc",ccc",ddd', (['aa, bb, cc','ccc"', 'ddd'], True)))
        for tc in test_cases:
            src = tc[0]
            canonic_dst = tc[1]
            test_dst = rbql_utils.split_escaped_csv_str(tc[0])
            self.assertEqual(canonic_dst, canonic_dst, msg = '\nsrc: {}\ntest_dst: {}\ncanonic_dst: {}\n'.format(src, test_dst, canonic_dst))


    def test_random(self):
        random_records = make_random_csv_records()
        for ir, rec in enumerate(random_records):
            canonic_fields = rec[0]
            escaped_entry = rec[1]
            canonic_warning = rec[2]
            test_fields, test_warning = rbql_utils.split_escaped_csv_str(escaped_entry)
            self.assertEqual(canonic_warning, test_warning)
            if not canonic_warning:
                self.assertEqual(canonic_fields, test_fields)


def make_random_csv_table(dst_path):
    random_records = make_random_csv_records()
    with open(dst_path, 'w') as dst:
        for rec in random_records:
            canonic_fields = rec[0]
            escaped_entry = rec[1]
            canonic_warning = rec[2]
            dst.write('{}\t{}\t{}\n'.format(escaped_entry, canonic_warning, ';'.join(canonic_fields)))


def test_random_csv_table(src_path):
    with open(src_path) as src:
        for line in src:
            line = line.rstrip('\n')
            rec = line.split('\t')
            assert len(rec) == 3
            escaped_entry = rec[0]
            canonic_warning = int(rec[1])
            canonic_fields = rec[2].split(';')
            test_fields, test_warning = rbql_utils.split_escaped_csv_str(escaped_entry)
            assert int(test_warning) == canonic_warning
            if not test_warning and (test_fields != canonic_fields):
                print( "Errror", file=sys.stderr) #FOR_DEBUG
                print( "escaped_entry:", escaped_entry, file=sys.stderr) #FOR_DEBUG
                print( "canonic_fields:", canonic_fields, file=sys.stderr) #FOR_DEBUG
                print( "test_fields:", test_fields, file=sys.stderr) #FOR_DEBUG
                sys.exit(1)



def make_random_bin_table(num_rows, num_cols, key_col1, key_col2, delim, dst_path):
    restricted_chars = ['\r', '\n'] + [delim]
    key_col = random.randint(0, num_cols - 1)
    good_keys1 = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta']
    good_keys2 = [str(v) for v in range(20)]
    result_table = list()
    for r in rbql.xrange6(num_rows):
        result_table.append(list())
        for c in rbql.xrange6(num_cols):
            if c == key_col1:
                result_table[-1].append(random.choice(good_keys1))
            elif c == key_col2:
                result_table[-1].append(random.choice(good_keys2))
            else:
                dice = random.randint(1, 20)
                if dice == 1:
                    result_table[-1].append(random.choice(good_keys1))
                elif dice == 2:
                    result_table[-1].append(random.choice(good_keys2))
                else:
                    result_table[-1].append(make_random_csv_entry(0, 20, restricted_chars))
    with codecs.open(dst_path, 'w', encoding='latin-1') as f:
        for row in result_table:
            f.write(delim.join(row))
            if random.randint(0, 2) == 0:
                f.write('\r\n')
            else:
                f.write('\n')


class TestParsing(unittest.TestCase):

    def test_literals_replacement(self):
        #TODO generate some random examples: Generate some strings randomly and then parse them
        test_cases = list()
        test_cases.append((r'Select 100 order by a1', []))
        test_cases.append((r'Select "hello" order by a1', ['"hello"']))
        test_cases.append((r"Select 'hello', 100 order by a1 desc", ["'hello'"]))
        test_cases.append((r'Select "hello", *, "world" 100 order by a1 desc', ['"hello"', '"world"']))
        test_cases.append((r'Select "hello", "world", "hello \" world", "hello \\\" world", "hello \\\\\\\" world" order by "world"', ['"hello"', '"world"', r'"hello \" world"', r'"hello \\\" world"', r'"hello \\\\\\\" world"', '"world"']))

        for tc in test_cases:
            format_expression, string_literals = rbql.separate_string_literals_py(tc[0])
            canonic_literals = tc[1]
            self.assertEqual(canonic_literals, string_literals)
            self.assertEqual(tc[0], rbql.combine_string_literals(format_expression, string_literals))

        query = r'Select `hello` order by a1'
        format_expression, string_literals = rbql.separate_string_literals_js(query)
        self.assertEqual(['`hello`'], string_literals)


    def test_separate_actions(self):
        query = 'select top   100 *, a2, a3 inner  join /path/to/the/file.tsv on a1 == b3 where a4 == "hello" and int(b3) == 100 order by int(a7) desc '
        canonic_res = {'INNER JOIN': {'text': '/path/to/the/file.tsv on a1 == b3'}, 'SELECT': {'text': '*, a2, a3', 'top': 100}, 'WHERE': {'text': 'a4 == "hello" and int(b3) == 100'}, 'ORDER BY': {'text': 'int(a7)', 'reverse': True}}
        test_res = rbql.separate_actions(query)
        assert test_res == canonic_res


    def test_join_parsing(self):
        join_part = '/path/to/the/file.tsv on a1 == b3'
        self.assertEqual(('/path/to/the/file.tsv', 'safe_get(afields, 1)', 'safe_get(bfields, 3)'), rbql.parse_join_expression(join_part))

        join_part = ' file.tsv on b20== a12  '
        self.assertEqual(('file.tsv', 'safe_get(afields, 12)', 'safe_get(bfields, 20)'), rbql.parse_join_expression(join_part))

        join_part = '/path/to/the/file.tsv on a1==a12  '
        with self.assertRaises(Exception) as cm:
            rbql.parse_join_expression(join_part)
        e = cm.exception
        self.assertTrue(str(e).find('Incorrect join syntax') != -1)

        join_part = ' Bon b1 == a12 '
        with self.assertRaises(Exception) as cm:
            rbql.parse_join_expression(join_part)
        e = cm.exception
        self.assertTrue(str(e).find('Incorrect join syntax') != -1)


    def test_column_vars_replacement(self):
        rbql_src = 'select top   100 *, a2,a3 inner  join /path/to/the/file.tsv on a1 == b3 where a4 == "hello" and int(b3) == 100 order by int(a7) desc '
        replaced = 'select top   100 *, safe_get(afields, 2),safe_get(afields, 3) inner  join /path/to/the/file.tsv on safe_get(afields, 1) == safe_get(bfields, 3) where safe_get(afields, 4) == "hello" and int(safe_get(bfields, 3)) == 100 order by int(safe_get(afields, 7)) desc '
        self.assertEqual(replaced, rbql.replace_column_vars(rbql_src))


    def test_update_translation(self):
        rbql_src = '  a1 =  a2  + b3, a2=a4  if b3 == a2 else a8, a8=   100, a30  =200/3 + 1  '
        test_dst = rbql.translate_update_expression(rbql_src, '    ')
        canonic_dst = list()
        canonic_dst.append('safe_set(afields, 1,  safe_get(afields, 2)  + safe_get(bfields, 3))')
        canonic_dst.append('    safe_set(afields, 2,safe_get(afields, 4)  if safe_get(bfields, 3) == safe_get(afields, 2) else safe_get(afields, 8))')
        canonic_dst.append('    safe_set(afields, 8,   100)')
        canonic_dst.append('    safe_set(afields, 30,200/3 + 1)')
        canonic_dst = '\n'.join(canonic_dst)
        self.assertEqual(canonic_dst, test_dst)


    def test_select_translation(self):
        rbql_src = ' *, a1,  a2,a1,*,*,b1, * ,   * '
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + [ safe_get(afields, 1),  safe_get(afields, 2),safe_get(afields, 1)] + star_fields + [] + star_fields + [safe_get(bfields, 1)] + star_fields + [] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *, a1,  a2,a1,*,*,*,b1, * ,   * '
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + [ safe_get(afields, 1),  safe_get(afields, 2),safe_get(afields, 1)] + star_fields + [] + star_fields + [] + star_fields + [safe_get(bfields, 1)] + star_fields + [] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' * '
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,* '
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + [] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,*, * '
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + [] + star_fields + [] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,*, * , *'
        test_dst = rbql.translate_select_expression_py(rbql_src)
        canonic_dst = '[] + star_fields + [] + star_fields + [] + star_fields + [] + star_fields + []'
        self.assertEqual(canonic_dst, test_dst)


        rbql_src = ' *, a1,  a2,a1,*,*,b1, * ,   * '
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([ safe_get(afields, 1),  safe_get(afields, 2),safe_get(afields, 1)]).concat(star_fields).concat([]).concat(star_fields).concat([safe_get(bfields, 1)]).concat(star_fields).concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *, a1,  a2,a1,*,*,*,b1, * ,   * '
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([ safe_get(afields, 1),  safe_get(afields, 2),safe_get(afields, 1)]).concat(star_fields).concat([]).concat(star_fields).concat([]).concat(star_fields).concat([safe_get(bfields, 1)]).concat(star_fields).concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' * '
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,* '
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,*, * '
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([]).concat(star_fields).concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)

        rbql_src = ' *,*, * , *'
        test_dst = rbql.translate_select_expression_js(rbql_src)
        canonic_dst = '[].concat([]).concat(star_fields).concat([]).concat(star_fields).concat([]).concat(star_fields).concat([]).concat(star_fields).concat([])'
        self.assertEqual(canonic_dst, test_dst)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--create_random_binary_table', metavar='FILE', help='create random binary table and write it to FILE')
    parser.add_argument('--create_random_csv_table', metavar='FILE', help='create random csv table and write it to FILE')
    parser.add_argument('--test_random_csv_table', metavar='FILE', help='test split method using samples from FILE')
    args = parser.parse_args()
    if args.create_random_binary_table is not None:
        dst_path = args.create_random_binary_table
        make_random_bin_table(1000, 4, 1, 3, '\t', dst_path)
    if args.create_random_csv_table is not None:
        dst_path = args.create_random_csv_table
        make_random_csv_table(dst_path)
    if args.test_random_csv_table is not None:
        src_path = args.test_random_csv_table
        test_random_csv_table(src_path)



if __name__ == '__main__':
    main()

