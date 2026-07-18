/*
 * Native AppKit CFBundleExecutable for MessageManager.app.
 *
 * Stays an NSApplication for the Dock (stops the bounce), copies Messages +
 * Contacts under Full Disk Access, then runs launch.sh as a child task.
 */
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <copyfile.h>
#include <dirent.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <sys/stat.h>
#include <unistd.h>

static void join2(char *out, size_t n, const char *a, const char *b) {
  snprintf(out, n, "%s/%s", a, b);
}

static int ensure_dir(const char *path) {
  char tmp[PATH_MAX];
  snprintf(tmp, sizeof(tmp), "%s", path);
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
    fprintf(stderr, "MessageManager: copy failed %s -> %s\n", src, dst);
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
  char src_root[PATH_MAX], sources_src[PATH_MAX], sources_dst[PATH_MAX];
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

static BOOL resolve_paths(char *script_out, size_t script_n,
                          char *messages_cache, size_t messages_n,
                          char *contacts_cache, size_t contacts_n) {
  char exe[PATH_MAX];
  uint32_t size = sizeof(exe);
  if (_NSGetExecutablePath(exe, &size) != 0) return NO;
  char resolved[PATH_MAX];
  if (!realpath(exe, resolved)) {
    strncpy(resolved, exe, sizeof(resolved) - 1);
    resolved[sizeof(resolved) - 1] = '\0';
  }

  char macos_dir[PATH_MAX];
  strncpy(macos_dir, resolved, sizeof(macos_dir) - 1);
  macos_dir[sizeof(macos_dir) - 1] = '\0';
  char *slash = strrchr(macos_dir, '/');
  if (!slash) return NO;
  *slash = '\0';

  char script[PATH_MAX];
  snprintf(script, sizeof(script), "%s/../Resources/app/scripts/macos/launch.sh", macos_dir);
  if (!realpath(script, script_out)) return NO;

  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";
  snprintf(messages_cache, messages_n,
           "%s/Library/Application Support/MessageManager/messages-cache", home);
  snprintf(contacts_cache, contacts_n,
           "%s/Library/Application Support/MessageManager/contacts-cache", home);

  refresh_messages_cache(home, messages_cache);
  refresh_contacts_cache(home, contacts_cache);
  setenv("THREAD_LEDGER_MESSAGES_CACHE", messages_cache, 1);
  setenv("THREAD_LEDGER_CONTACTS_CACHE", contacts_cache, 1);
  setenv("THREAD_LEDGER_MANAGED", "1", 1);
  return YES;
}

@interface MMAppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSTask *launchTask;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, copy) NSString *baseURL;
@end

@implementation MMAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
  (void)notification;
  self.baseURL = @"http://127.0.0.1:8741";
  [self buildWindow];
  [self startLaunchScript];
  self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:2.0
                                                    target:self
                                                  selector:@selector(pollServer)
                                                  userInfo:nil
                                                   repeats:YES];
}

- (void)buildWindow {
  NSRect frame = NSMakeRect(0, 0, 420, 168);
  self.window = [[NSWindow alloc] initWithContentRect:frame
                                            styleMask:(NSWindowStyleMaskTitled |
                                                       NSWindowStyleMaskClosable |
                                                       NSWindowStyleMaskMiniaturizable)
                                              backing:NSBackingStoreBuffered
                                                defer:NO];
  self.window.title = @"MessageManager";
  self.window.releasedWhenClosed = NO;
  [self.window center];

  NSView *content = self.window.contentView;
  NSTextField *title = [NSTextField labelWithString:@"MessageManager is running"];
  title.font = [NSFont boldSystemFontOfSize:15];
  title.translatesAutoresizingMaskIntoConstraints = NO;

  NSTextField *body = [NSTextField wrappingLabelWithString:
      @"The app is open in your browser. Keep this window open while you work.\n"
       @"Click Quit to stop the local server."];
  body.translatesAutoresizingMaskIntoConstraints = NO;

  NSButton *quit = [NSButton buttonWithTitle:@"Quit MessageManager"
                                      target:self
                                      action:@selector(quitApp:)];
  quit.bezelStyle = NSBezelStyleRounded;
  quit.keyEquivalent = @"q";
  quit.keyEquivalentModifierMask = NSEventModifierFlagCommand;
  quit.translatesAutoresizingMaskIntoConstraints = NO;

  [content addSubview:title];
  [content addSubview:body];
  [content addSubview:quit];

  [NSLayoutConstraint activateConstraints:@[
    [title.topAnchor constraintEqualToAnchor:content.topAnchor constant:18],
    [title.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:20],
    [title.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-20],
    [body.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:10],
    [body.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
    [body.trailingAnchor constraintEqualToAnchor:title.trailingAnchor],
    [quit.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-20],
    [quit.bottomAnchor constraintEqualToAnchor:content.bottomAnchor constant:-16],
  ]];

  [self.window makeKeyAndOrderFront:nil];
  [NSApp activateIgnoringOtherApps:YES];
}

- (void)startLaunchScript {
  char script[PATH_MAX], messages_cache[PATH_MAX], contacts_cache[PATH_MAX];
  if (!resolve_paths(script, sizeof(script), messages_cache, sizeof(messages_cache),
                     contacts_cache, sizeof(contacts_cache))) {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"MessageManager failed to launch";
    alert.informativeText = @"Could not find launch.sh inside the app bundle.";
    [alert runModal];
    [NSApp terminate:nil];
    return;
  }

  NSTask *task = [[NSTask alloc] init];
  task.executableURL = [NSURL fileURLWithPath:@"/bin/bash"];
  task.arguments = @[ [NSString stringWithUTF8String:script] ];
  task.environment = [[NSProcessInfo processInfo] environment];
  MMAppDelegate *strongSelf = self;
  task.terminationHandler = ^(NSTask *finished) {
    dispatch_async(dispatch_get_main_queue(), ^{
      // Managed mode exits after starting the server; keep the app alive.
      if (finished.terminationStatus != 0) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"MessageManager failed to start";
        alert.informativeText =
            @"Check ~/Library/Application Support/MessageManager/logs/launch.log";
        [alert runModal];
        [NSApp terminate:nil];
      }
      (void)strongSelf;
    });
  };

  NSError *error = nil;
  if (![task launchAndReturnError:&error]) {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"MessageManager failed to launch";
    alert.informativeText = error.localizedDescription ?: @"Unknown error";
    [alert runModal];
    [NSApp terminate:nil];
    return;
  }
  self.launchTask = task;
}

- (void)pollServer {
  // If the server dies while the control window is open, exit cleanly.
  static BOOL sawUp = NO;
  NSURL *url = [NSURL URLWithString:[self.baseURL stringByAppendingString:@"/api/health"]];
  NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url
                                                     cachePolicy:NSURLRequestReloadIgnoringLocalCacheData
                                                 timeoutInterval:1.5];
  NSURLSessionDataTask *task =
      [[NSURLSession sharedSession] dataTaskWithRequest:req
                                      completionHandler:^(NSData *data, NSURLResponse *response, NSError *err) {
                                        (void)data;
                                        BOOL up = (err == nil && [(NSHTTPURLResponse *)response statusCode] == 200);
                                        dispatch_async(dispatch_get_main_queue(), ^{
                                          if (up) {
                                            sawUp = YES;
                                            return;
                                          }
                                          if (sawUp) {
                                            [NSApp terminate:nil];
                                          }
                                        });
                                      }];
  [task resume];
}

- (void)requestShutdown {
  NSURL *url = [NSURL URLWithString:[self.baseURL stringByAppendingString:@"/api/shutdown"]];
  NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url];
  req.HTTPMethod = @"POST";
  req.HTTPBody = [NSData data];
  req.timeoutInterval = 3.0;
  NSURLSessionDataTask *task =
      [[NSURLSession sharedSession] dataTaskWithRequest:req
                                      completionHandler:^(NSData *data, NSURLResponse *response, NSError *err) {
                                        (void)data;
                                        (void)response;
                                        (void)err;
                                      }];
  [task resume];
  // Brief pause so the request can leave before we tear down the process.
  usleep(250000);
}

- (void)quitApp:(id)sender {
  (void)sender;
  [self requestShutdown];
  if (self.launchTask.isRunning) {
    [self.launchTask terminate];
  }
  [NSApp terminate:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
  (void)sender;
  [self requestShutdown];
  return YES;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
  (void)sender;
  [self.pollTimer invalidate];
  [self requestShutdown];
  return NSTerminateNow;
}

@end

int main(int argc, const char *argv[]) {
  @autoreleasepool {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    MMAppDelegate *delegate = [[MMAppDelegate alloc] init];
    NSApp.delegate = delegate;
    // NSApplicationMain finishes launching (stops Dock bounce) and runs the app.
    return NSApplicationMain(argc, argv);
  }
}
