import 'package:flutter/foundation.dart';

import '../models/models.dart';
import '../repositories/data_repository.dart';

class AppState extends ChangeNotifier {
  final DataRepository repository;

  bool isLoaded = false;
  List<Story> stories = [];
  List<ChatThread> chatThreads = [];

  AppState({required this.repository});

  Future<void> load() async {
    if (isLoaded) {
      return;
    }

    stories = _initialStories;
    chatThreads = _initialThreads;
    isLoaded = true;
    notifyListeners();

    final storiesFromStorage = await repository.fetchStories();
    final threadsFromStorage = await repository.fetchChatThreads();

    var updated = false;
    if (storiesFromStorage.isNotEmpty) {
      stories = storiesFromStorage;
      updated = true;
    }
    if (threadsFromStorage.isNotEmpty) {
      chatThreads = threadsFromStorage;
      updated = true;
    }
    if (updated) {
      notifyListeners();
    }

    try {
      await repository.syncAll();
    } catch (_) {
      // Remote sync remains optional on this prototype.
    }
  }

  Future<void> addStory(Story story) async {
    stories.insert(0, story);
    await repository.saveStories(stories);
    notifyListeners();
  }

  Future<void> updateThread(ChatThread thread) async {
    final index = chatThreads.indexWhere((item) => item.id == thread.id);
    if (index != -1) {
      chatThreads[index] = thread;
      await repository.saveChatThreads(chatThreads);
      notifyListeners();
    }
  }

  Future<void> addMessageToThread(String threadId, ChatMessage message) async {
    final index = chatThreads.indexWhere((item) => item.id == threadId);
    if (index != -1) {
      final existing = chatThreads[index];
      final updated = ChatThread(
        id: existing.id,
        title: existing.title,
        subtitle: message.text,
        participants: existing.participants,
        unreadCount: existing.unreadCount,
        lastUpdated: message.timestamp,
        messages: [...existing.messages, message],
      );
      chatThreads[index] = updated;
      await repository.saveChatThreads(chatThreads);
      notifyListeners();
    }
  }

  List<Story> get storiesWithMore => stories;

  final List<Story> _initialStories = [
    Story(
      id: 'story_1',
      title: 'Мото-мандрівка',
      author: 'Андрій',
      authorAvatarUrl: null,
      location: 'Карпати',
      description: 'Переїзд через гори, нічний табір і враження від дороги.',
      imagePath: null,
      imageUrl: 'https://picsum.photos/seed/story1/500/500',
      videoPath: null,
      videoUrl: null,
      likes: 128,
      views: 540,
      createdAt: DateTime.now().subtract(const Duration(days: 1)),
      updatedAt: DateTime.now().subtract(const Duration(days: 1)),
    ),
    Story(
      id: 'story_2',
      title: 'Відео з вечірки',
      author: 'Марія',
      authorAvatarUrl: null,
      location: 'Київ',
      description: 'Нова вечірка спільноти з яскравими моментами.',
      imagePath: null,
      imageUrl: null,
      videoPath: null,
      videoUrl: 'https://flutter.github.io/assets-for-api-docs/assets/videos/bee.mp4',
      likes: 98,
      views: 420,
      createdAt: DateTime.now().subtract(const Duration(days: 2)),
      updatedAt: DateTime.now().subtract(const Duration(days: 2)),
    ),
    Story(
      id: 'story_3',
      title: 'Нова точка',
      author: 'RiderTeam',
      authorAvatarUrl: null,
      location: 'Лівий берег',
      description: 'Оновили маршрут для вечірніх поїздок.',
      imagePath: null,
      imageUrl: 'https://picsum.photos/seed/story3/500/500',
      videoPath: null,
      videoUrl: null,
      likes: 214,
      views: 760,
      createdAt: DateTime.now().subtract(const Duration(days: 3)),
      updatedAt: DateTime.now().subtract(const Duration(days: 3)),
    ),
    Story(
      id: 'story_4',
      title: 'Райдери Київ',
      author: 'Олександр',
      authorAvatarUrl: null,
      location: 'Київ',
      description: 'Підготовка до вечірньої зустрічі.',
      imagePath: null,
      imageUrl: 'https://picsum.photos/seed/story4/500/500',
      videoPath: null,
      videoUrl: null,
      likes: 183,
      views: 605,
      createdAt: DateTime.now().subtract(const Duration(days: 4)),
      updatedAt: DateTime.now().subtract(const Duration(days: 4)),
    ),
  ];

  final List<ChatThread> _initialThreads = [
    ChatThread(
      id: 'chat_igor',
      title: 'Ігор',
      subtitle: 'Бачиш точку збору? Заїжджаю о 19:45',
      participants: ['Я', 'Ігор'],
      unreadCount: 0,
      lastUpdated: DateTime.now().subtract(const Duration(hours: 1, minutes: 10)),
      messages: [
        ChatMessage(
          id: 'msg_igor_1',
          sender: 'Ігор',
          text: 'Бачиш точку збору? Заїждую о 19:45',
          type: ChatMessageType.text,
          timestamp: DateTime.now().subtract(const Duration(hours: 1, minutes: 15)),
          isMe: false,
          status: MessageStatus.read,
        ),
        ChatMessage(
          id: 'msg_igor_2',
          sender: 'Я',
          text: 'Так, бачу, буду на місці о 19:40.',
          type: ChatMessageType.text,
          timestamp: DateTime.now().subtract(const Duration(hours: 1, minutes: 10)),
          isMe: true,
          status: MessageStatus.sent,
        ),
      ],
    ),
    ChatThread(
      id: 'chat_marina',
      title: 'Марина',
      subtitle: 'Додавайся до вечірнього маршруту',
      participants: ['Я', 'Марина'],
      unreadCount: 1,
      lastUpdated: DateTime.now().subtract(const Duration(hours: 2, minutes: 10)),
      messages: [
        ChatMessage(
          id: 'msg_marina_1',
          sender: 'Марина',
          text: 'Додавайся до вечірнього маршруту',
          type: ChatMessageType.text,
          timestamp: DateTime.now().subtract(const Duration(hours: 2, minutes: 20)),
          isMe: false,
          status: MessageStatus.delivered,
        ),
        ChatMessage(
          id: 'msg_marina_2',
          sender: 'Я',
          text: 'Клас, покажи маршрут і час.',
          type: ChatMessageType.text,
          timestamp: DateTime.now().subtract(const Duration(hours: 2, minutes: 10)),
          isMe: true,
          status: MessageStatus.sent,
        ),
      ],
    ),
    ChatThread(
      id: 'chat_riderteam',
      title: 'RiderTeam',
      subtitle: 'Нове відео зі зустрічі очікується',
      participants: ['Я', 'RiderTeam'],
      unreadCount: 2,
      lastUpdated: DateTime.now().subtract(const Duration(hours: 3, minutes: 45)),
      messages: [
        ChatMessage(
          id: 'msg_riderteam_1',
          sender: 'RiderTeam',
          text: 'Нове відео зі зустрічі очікується',
          type: ChatMessageType.text,
          timestamp: DateTime.now().subtract(const Duration(hours: 3, minutes: 45)),
          isMe: false,
          status: MessageStatus.delivered,
        ),
      ],
    ),
  ];
}
