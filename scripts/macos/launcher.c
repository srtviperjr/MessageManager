/*
 * Native CFBundleExecutable for MessageManager.app.
 *
 * Full Disk Access is granted to this Mach-O binary (the app). A shell-script
 * executable cannot reliably pass that permission to a child Python process, so
 * this launcher copies Messages + Contacts databases into Application Support
 * and then starts the Python server via launch.sh.
 */
#include <copyfile.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void join2(char *out, size_t n, const char *a, const char *b) {
  snprintf(out, n, "%s/%s", a, b);
}

static int ensure_dir(const char *path) {
  char tmp[PATH_MAX];
  snprintf(tmp, sizeof(tmp), "%s", path);
  size_t len = strlen(tmp);
  if (len == 0) return -1;
  for (char *p = tmp + 1; *p; p++) {
    if (*p == '/') {
      *p = '\0';
      mkdir(tmp, 0755);
      *p = '/';
    }
  }
  return mkdir(tmp, 0755);
}

static void copy_if_exists(const char *src, const char *dst) {
  struct stat st;
  if (stat(src, &st) != 0) return;
  if (copyfile(src, dst, NULL, COPYFILE_ALL) != 0) {
    fprintf(stderr, "MessageManager: copy failed %s -> %s (%s)\n", src, dst, strerror(errno));
  }
}

static void copy_db_trio(const char *src_db, const char *dst_db) {
  char src[PATH_MAX], dst[PATH_MAX];
  copy_if_exists(src_db, dst_db);

  snprintf(src, sizeof(src), "%s-wal", src_db);
  snprintf(dst, sizeof(dst), "%s-wal", dst_db);
  copy_if_exists(src, dst);

  snprintf(src, sizeof(src), "%s-shm", src_db);
  snprintf(dst, sizeof(dst), "%s-shm", dst_db);
  copy_if_exists(src, dst);
}

static void refresh_messages_cache(const char *home, const char *cache_dir) {
  char src[PATH_MAX], dst[PATH_MAX];
  ensure_dir(cache_dir);

  join2(src, sizeof(src), home, "Library/Messages/chat.db");
  join2(dst, sizeof(dst), cache_dir, "chat.db");
  copy_db_trio(src, dst);
}

static void refresh_contacts_cache(const char *home, const char *cache_dir) {
  char src_root[PATH_MAX], dst_root[PATH_MAX];
  char sources_src[PATH_MAX], sources_dst[PATH_MAX];
  char db_src[PATH_MAX], db_dst[PATH_MAX];

  ensure_dir(cache_dir);

  join2(src_root, sizeof(src_root), home, "Library/Application Support/AddressBook");
  join2(db_src, sizeof(db_src), src_root, "AddressBook-v22.abcddb");
  join2(db_dst, sizeof(db_dst), cache_dir, "AddressBook-v22.abcddb");
  copy_db_trio(db_src, db_dst);

  join2(sources_src, sizeof(sources_src), src_root, "Sources");
  join2(sources_dst, sizeof(sources_dst), cache_dir, "Sources");
  ensure_dir(sources_dst);

  DIR *dir = opendir(sources_src);
  if (!dir) return;
  struct dirent *ent;
  while ((ent = readdir(dir)) != NULL) {
    if (ent->d_name[0] == '.') continue;
    char child_src[PATH_MAX], child_dst[PATH_MAX];
    join2(child_src, sizeof(child_src), sources_src, ent->d_name);
    join2(child_dst, sizeof(child_dst), sources_dst, ent->d_name);

    struct stat st;
    if (stat(child_src, &st) != 0 || !S_ISDIR(st.st_mode)) continue;
    ensure_dir(child_dst);

    join2(db_src, sizeof(db_src), child_src, "AddressBook-v22.abcddb");
    join2(db_dst, sizeof(db_dst), child_dst, "AddressBook-v22.abcddb");
    copy_db_trio(db_src, db_dst);
  }
  closedir(dir);
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  char exe[PATH_MAX];
  uint32_t size = sizeof(exe);
  if (_NSGetExecutablePath(exe, &size) != 0) {
    fprintf(stderr, "MessageManager: cannot resolve executable path\n");
    return 1;
  }
  char resolved[PATH_MAX];
  if (!realpath(exe, resolved)) {
    strncpy(resolved, exe, sizeof(resolved) - 1);
    resolved[sizeof(resolved) - 1] = '\0';
  }

  char macos_dir[PATH_MAX];
  strncpy(macos_dir, resolved, sizeof(macos_dir) - 1);
  macos_dir[sizeof(macos_dir) - 1] = '\0';
  char *slash = strrchr(macos_dir, '/');
  if (!slash) return 1;
  *slash = '\0';

  char script[PATH_MAX];
  snprintf(script, sizeof(script), "%s/../Resources/app/scripts/macos/launch.sh", macos_dir);
  char script_real[PATH_MAX];
  if (!realpath(script, script_real)) {
    fprintf(stderr, "MessageManager: launch.sh missing at %s\n", script);
    return 1;
  }

  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";

  char messages_cache[PATH_MAX];
  char contacts_cache[PATH_MAX];
  snprintf(
      messages_cache,
      sizeof(messages_cache),
      "%s/Library/Application Support/MessageManager/messages-cache",
      home);
  snprintf(
      contacts_cache,
      sizeof(contacts_cache),
      "%s/Library/Application Support/MessageManager/contacts-cache",
      home);

  refresh_messages_cache(home, messages_cache);
  refresh_contacts_cache(home, contacts_cache);

  setenv("THREAD_LEDGER_MESSAGES_CACHE", messages_cache, 1);
  setenv("THREAD_LEDGER_CONTACTS_CACHE", contacts_cache, 1);

  execl("/bin/bash", "bash", script_real, (char *)NULL);
  fprintf(stderr, "MessageManager: failed to exec launch.sh (%s)\n", strerror(errno));
  return 1;
}
