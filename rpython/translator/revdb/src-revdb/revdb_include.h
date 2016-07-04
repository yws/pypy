#include <string.h>

/* By default, this makes an executable which supports both recording
   and replaying.  It should help avoid troubles like using for
   replaying an executable that is slightly different than the one
   used for recording.  In theory you can compile with
   -DRPY_RDB_REPLAY=0 or -DRPY_RDB_REPLAY=1 to get only one version
   compiled for it, which should be slightly faster (not tested so
   far).
*/

typedef struct {
#ifndef RPY_RDB_REPLAY
    bool_t replay;
#define RPY_RDB_REPLAY   rpy_revdb.replay
#define RPY_RDB_DYNAMIC_REPLAY
#endif
    bool_t watch_enabled;
    char *buf_p, *buf_limit, *buf_readend;
    uint64_t stop_point_seen, stop_point_break;
    uint64_t unique_id_seen, unique_id_break;
} rpy_revdb_t;

RPY_EXTERN rpy_revdb_t rpy_revdb;


/* ------------------------------------------------------------ */

RPY_EXTERN void rpy_reverse_db_setup(int *argc_p, char **argv_p[]);
RPY_EXTERN void rpy_reverse_db_teardown(void);

#if 0    /* enable to print locations to stderr of all the EMITs */
#  define _RPY_REVDB_PRINT(mode, _e)                                    \
    fprintf(stderr,                                                     \
            "%s:%d: %0*llx\n",                                          \
            __FILE__, __LINE__, 2 * sizeof(_e),                         \
            ((unsigned long long)_e) & ((2ULL << (8*sizeof(_e)-1)) - 1))
#endif

#if 0    /* enable to print all mallocs to stderr */
RPY_EXTERN void seeing_uid(uint64_t uid);
#  define _RPY_REVDB_PRUID()                                    \
    seeing_uid(uid);                                            \
    fprintf(stderr,                                             \
            "%s:%d: obj %llu\n",                                \
            __FILE__, __LINE__, (unsigned long long) uid)
#endif

#ifndef _RPY_REVDB_PRINT
#  define _RPY_REVDB_PRINT(mode, _e)  /* nothing */
#endif
#ifndef _RPY_REVDB_PRUID
#  define _RPY_REVDB_PRUID()      /* nothing */
#endif


#define _RPY_REVDB_EMIT_RECORD(decl_e, variable)                        \
        {                                                               \
            decl_e = variable;                                          \
            _RPY_REVDB_PRINT("write", _e);                              \
            memcpy(rpy_revdb.buf_p, &_e, sizeof(_e));                   \
            if ((rpy_revdb.buf_p += sizeof(_e)) > rpy_revdb.buf_limit)  \
                rpy_reverse_db_flush();                                 \
        }

#define _RPY_REVDB_EMIT_REPLAY(decl_e, variable)                        \
        {                                                               \
            decl_e;                                                     \
            char *_src = rpy_revdb.buf_p;                               \
            char *_end1 = _src + sizeof(_e);                            \
            memcpy(&_e, _src, sizeof(_e));                              \
            rpy_revdb.buf_p = _end1;                                    \
            _RPY_REVDB_PRINT("read", _e);                               \
            if (_end1 >= rpy_revdb.buf_limit)                           \
                rpy_reverse_db_fetch(__FILE__, __LINE__);               \
            variable = _e;                                              \
        }

#define RPY_REVDB_EMIT(normal_code, decl_e, variable)                   \
    if (!RPY_RDB_REPLAY) {                                              \
        normal_code                                                     \
        _RPY_REVDB_EMIT_RECORD(decl_e, variable)                        \
    } else                                                              \
        _RPY_REVDB_EMIT_REPLAY(decl_e, variable)

#define RPY_REVDB_EMIT_VOID(normal_code)                                \
    if (!RPY_RDB_REPLAY) { normal_code } else { }

#define RPY_REVDB_CALL(call_code, decl_e, variable)                     \
    if (!RPY_RDB_REPLAY) {                                              \
        call_code                                                       \
        _RPY_REVDB_EMIT_RECORD(unsigned char _e, 0xFC)                  \
        _RPY_REVDB_EMIT_RECORD(decl_e, variable)                        \
    } else {                                                            \
        unsigned char _re;                                              \
        _RPY_REVDB_EMIT_REPLAY(unsigned char _e, _re)                   \
        if (_re != 0xFC)                                                \
            rpy_reverse_db_invoke_callback(_re);                        \
        _RPY_REVDB_EMIT_REPLAY(decl_e, variable)                        \
    }

#define RPY_REVDB_CALL_VOID(call_code)                                  \
    if (!RPY_RDB_REPLAY) {                                              \
        call_code                                                       \
        _RPY_REVDB_EMIT_RECORD(unsigned char _e, 0xFC)                  \
    }                                                                   \
    else {                                                              \
        unsigned char _re;                                              \
        _RPY_REVDB_EMIT_REPLAY(unsigned char _e, _re)                   \
        if (_re != 0xFC)                                                \
            rpy_reverse_db_invoke_callback(_re);                        \
    }

#define RPY_REVDB_CALLBACKLOC(locnum)                                   \
    rpy_reverse_db_callback_loc(locnum)

#define RPY_REVDB_REC_UID(expr)                                         \
    do {                                                                \
        uint64_t uid = rpy_revdb.unique_id_seen;                        \
        if (uid == rpy_revdb.unique_id_break || !expr)                  \
            uid = rpy_reverse_db_unique_id_break(expr);                 \
        rpy_revdb.unique_id_seen = uid + 1;                             \
        ((struct pypy_header0 *)expr)->h_uid = uid;                     \
        _RPY_REVDB_PRUID();                                             \
    } while (0)

#define OP_REVDB_STOP_POINT(r)                                          \
    if (++rpy_revdb.stop_point_seen == rpy_revdb.stop_point_break)      \
        rpy_reverse_db_stop_point()

#define OP_REVDB_SEND_ANSWER(cmd, arg1, arg2, arg3, ll_string, r)       \
    rpy_reverse_db_send_answer(cmd, arg1, arg2, arg3, ll_string)

#define OP_REVDB_BREAKPOINT(num, r)                                     \
    rpy_reverse_db_breakpoint(num)

#define OP_REVDB_GET_VALUE(value_id, r)                                 \
    r = rpy_reverse_db_get_value(value_id)

#define OP_REVDB_IDENTITYHASH(obj, r)                                   \
    r = rpy_reverse_db_identityhash((struct pypy_header0 *)(obj))

#define OP_REVDB_GET_UNIQUE_ID(x, r)                                    \
    r = ((struct pypy_header0 *)x)->h_uid

#define OP_REVDB_TRACK_OBJECT(uid, callback, r)                         \
    rpy_reverse_db_track_object(uid, callback)

#define OP_REVDB_WATCH_SAVE_STATE(r)   do {                             \
        r = rpy_revdb.watch_enabled;                                    \
        if (r) rpy_reverse_db_watch_save_state();                       \
    } while (0)

#define OP_REVDB_WATCH_RESTORE_STATE(any_watch_point, r)                \
    rpy_reverse_db_watch_restore_state(any_watch_point)

#define OP_REVDB_WEAKREF_CREATE(target, r)                              \
    r = rpy_reverse_db_weakref_create(target)

#define OP_REVDB_WEAKREF_DEREF(weakref, r)                              \
    r = rpy_reverse_db_weakref_deref(weakref)

#define OP_REVDB_CALL_DESTRUCTOR(obj, r)                                \
    rpy_reverse_db_call_destructor(obj)

/* Used only for getting a fast hash value that doesn't change too
   often (with the minimark GC, it changes at most once).  Here,
   we'll just return the UID. */
#define RPY_REVDB_CAST_PTR_TO_INT(obj)   (((struct pypy_header0 *)obj)->h_uid)


RPY_EXTERN void rpy_reverse_db_flush(void);
RPY_EXTERN void rpy_reverse_db_fetch(const char *file, int line);
RPY_EXTERN void rpy_reverse_db_stop_point(void);
RPY_EXTERN void rpy_reverse_db_send_answer(int cmd, int64_t arg1, int64_t arg2,
                                           int64_t arg3, RPyString *extra);
RPY_EXTERN Signed rpy_reverse_db_identityhash(struct pypy_header0 *obj);
RPY_EXTERN void rpy_reverse_db_breakpoint(int64_t num);
RPY_EXTERN long long rpy_reverse_db_get_value(char value_id);
RPY_EXTERN uint64_t rpy_reverse_db_unique_id_break(void *new_object);
RPY_EXTERN void rpy_reverse_db_watch_save_state(void);
RPY_EXTERN void rpy_reverse_db_watch_restore_state(bool_t any_watch_point);
RPY_EXTERN void *rpy_reverse_db_weakref_create(void *target);
RPY_EXTERN void *rpy_reverse_db_weakref_deref(void *weakref);
RPY_EXTERN int rpy_reverse_db_fq_register(void *obj);
RPY_EXTERN void *rpy_reverse_db_next_dead(void *result);
RPY_EXTERN void rpy_reverse_db_register_destructor(void *obj, void(*)(void *));
RPY_EXTERN void rpy_reverse_db_call_destructor(void *obj);
RPY_EXTERN void rpy_reverse_db_invoke_callback(unsigned char);
RPY_EXTERN void rpy_reverse_db_callback_loc(int);

/* ------------------------------------------------------------ */