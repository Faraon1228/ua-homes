import 'package:hive/hive.dart';

import '../models/models.dart';

class HiveStorageService {
  static const _storiesBoxName = 'stories_box';
  static const _chatThreadsBoxName = 'chat_threads_box';

  Future<Box<Story>> get _storiesBox async {
    return await Hive.openBox<Story>(_storiesBoxName);
  }

  Future<Box<ChatThread>> get _chatThreadsBox async {
    return await Hive.openBox<ChatThread>(_chatThreadsBoxName);
  }

  Future<List<Story>> loadStories() async {
    final box = await _storiesBox;
    return box.values.toList();
  }

  Future<List<ChatThread>> loadChatThreads() async {
    final box = await _chatThreadsBox;
    return box.values.toList();
  }

  Future<void> saveStories(List<Story> stories) async {
    final box = await _storiesBox;
    await box.clear();
    for (var story in stories) {
      await box.add(story);
    }
  }

  Future<void> saveChatThreads(List<ChatThread> threads) async {
    final box = await _chatThreadsBox;
    await box.clear();
    for (var thread in threads) {
      await box.add(thread);
    }
  }
}
