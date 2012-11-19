'''
functioncache

functioncache is a decorator which saves the return value of functions even
after the interpreter dies. For example this is useful on functions that download
and parse webpages. All you need to do is specify how long
the return values should be cached (use seconds, like time.sleep).

USAGE:

    from functioncache import functioncache
    
    @functioncache(24 * 60 * 60)
    def time_consuming_function(args):
        # etc
    
    @functioncache(functioncache.YEAR)
    def another_function(args):
        # etc


NOTE: All arguments of the decorated function and the return value need to be
    picklable for this to work.

NOTE: The cache isn't automatically cleaned, it is only overwritten. If your
    function can receive many different arguments that rarely repeat, your
    cache may forever grow. One day I might add a feature that once in every
    100 calls scans the db for outdated stuff and erases.

NOTE: This is less useful on methods of a class because the instance (self)
    is cached, and if the instance isn't the same, the cache isn't used. This
    makes sense because class methods are affected by changes in whatever
    is attached to self.

Tested on python 2.7 and 3.1

License: BSD, do what you wish with this. Could be awesome to hear if you found
it useful and/or you have suggestions. ubershmekel at gmail


A trick to invalidate a single value:

    @functioncache.functioncache
    def somefunc(x, y, z):
        return x * y * z
        
    del somefunc._db[functioncache._args_key(somefunc, (1,2,3), {})]
    # or just iterate of somefunc._db (it's a shelve, like a dict) to find the right key.


'''


import collections as _collections
import datetime as _datetime
import functools as _functools
import inspect as _inspect
import os as _os
import pickle as _pickle
import shelve as _shelve
import sys as _sys
import time as _time
import traceback as _traceback
import types

_retval = _collections.namedtuple('_retval', 'timesig data')
_SRC_DIR = _os.path.dirname(_os.path.abspath(__file__))

SECOND = 1
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = 7 * DAY
MONTH = 30 * DAY
YEAR = 365 * DAY
FOREVER = None

OPEN_DBS = dict()

def _get_cache_name(function):
    """
    returns a name for the module's cache db.
    """
    module_name = _inspect.getfile(function)
    cache_name = module_name
    
    # fix for '<string>' or '<stdin>' in exec or interpreter usage.
    cache_name = cache_name.replace('<', '_lt_')
    cache_name = cache_name.replace('>', '_gt_')
    
    cache_name += '.cache'
    return cache_name


def _log_error(error_str):
    try:
        error_log_fname = _os.path.join(_SRC_DIR, 'functioncache.err.log')
        if _os.path.isfile(error_log_fname):
            fhand = open(error_log_fname, 'a')
        else:
            fhand = open(error_log_fname, 'w')
        fhand.write('[%s] %s\r\n' % (_datetime.datetime.now().isoformat(), error_str))
        fhand.close()
    except Exception:
        pass

def _args_key(function, args, kwargs):
    arguments = (args, kwargs)
    # Check if you have a valid, cached answer, and return it.
    # Sadly this is python version dependant
    if _sys.version_info[0] == 2:
        arguments_pickle = _pickle.dumps(arguments)
    else:
        # NOTE: protocol=0 so it's ascii, this is crucial for py3k
        #       because shelve only works with proper strings.
        #       Otherwise, we'd get an exception because
        #       function.__name__ is str but dumps returns bytes.
        arguments_pickle = _pickle.dumps(arguments, protocol=0).decode('ascii')
        
    key = function.__name__ + arguments_pickle
    return key

class FunctioncacheShelveBackend(object) :
    def __init__(self, function) :
        self.shelve = _shelve.open(cache_name)
    
    def __in__(self, key) :
        return key in self.shelve
    
    def __getattr__(self, key) :
        return self.shelve[key]
    
    def __setattr__(self, key, value) :
        # NOTE: no need to _db.sync() because there was no mutation
        # NOTE: it's importatnt to do _db.sync() because otherwise the cache doesn't survive Ctrl-Break!
        self.shelve[key] = _retval(_time.time(), retval)
        self.shelve.sync()

def mkdir_p(path) :
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

import hashlib
class FunctioncacheFileBackend(object) :
    def __init__(self, function) :
        module_name = _inspect.getfile(function)
        cache_name = module_name
        
        # fix for '<string>' or '<stdin>' in exec or interpreter usage.
        cache_name = cache_name.replace('<', '_lt_')
        cache_name = cache_name.replace('>', '_gt_')
        
        cache_name += '.cache'
        
        self.dir_name = cache_name
        mkdir_p(self.dir_name)

    def __in__(self, key) :
        return os.path.isfile(self.get_filename(key))
    
    def __getattr(self, key) :
        return pickle.load(open(self.get_filename(key)))
    
    def __setattr(self, key, value) :
        pickle.dump(
            _retval(_time.time(), retval),
            open(self.get_filename(key), 'w'),
        )
    
    def get_filename(self, key) :
        # hash the key and use as a filename
        return self.dir_name + hashlib.sha1(key).hexdigest()

def functioncache(seconds_of_validity=None, fail_silently=False, DB=FunctioncacheShelveBackend):
    '''
    functioncache is called and the decorator should be returned.
    '''
    def functioncache_decorator(function):
        @_functools.wraps(function)
        def function_with_cache(*args, **kwargs):
            try:
                key = _args_key(function, args, kwargs)
                
                if key in function._db:
                    rv = function._db[key]
                    if seconds_of_validity is None or _time.time() - rv.timesig < seconds_of_validity:
                        return rv.data
            except Exception:
                # in any case of failure, don't let functioncache break the program
                error_str = _traceback.format_exc()
                _log_error(error_str)
                if not fail_silently:
                    raise
            
            retval = function(*args, **kwargs)

            # store in cache
            try:
                function._db[key] = _retval(_time.time(), retval)
            except Exception:
                # in any case of failure, don't let functioncache break the program
                error_str = _traceback.format_exc()
                _log_error(error_str)
                if not fail_silently:
                    raise
            
            return retval

        # make sure cache is loaded
        if not hasattr(function, '_db'):
            cache_name = _get_cache_name(function)
            if cache_name in OPEN_DBS:
                function._db = OPEN_DBS[cache_name]
            else:
                function._db = DB(function)
                OPEN_DBS[cache_name] = function._db
            
            function_with_cache._db = function._db
            
        return function_with_cache

    if type(seconds_of_validity) == types.FunctionType:
        # support for when people use '@functioncache.functioncache' instead of '@functioncache.functioncache()'
        func = seconds_of_validity
        return functioncache_decorator(func)
    
    return functioncache_decorator