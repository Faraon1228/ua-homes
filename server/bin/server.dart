// ignore_for_file: implicit_call_tearoffs

import 'dart:convert';
import 'dart:io';

import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart';
import 'package:shelf_router/shelf_router.dart';

const _storageFile = 'storage.json';
const _host = '0.0.0.0';
const _port = 8080;

Future<void> main() async {
  final storage = File(_storageFile);
  final state = await _loadState(storage);

  final router = Router()
    ..get('/', (Request request) => Response.ok('DriveCommunity sync server is running'))
    ..get('/api/stories', (Request request) => Response.ok(
          jsonEncode({'stories': state['stories']}),
          headers: {'content-type': 'application/json'},
        ))
    ..get('/api/chat_threads', (Request request) => Response.ok(
          jsonEncode({'chatThreads': state['chatThreads']}),
          headers: {'content-type': 'application/json'},
        ))
    ..post('/api/stories', (Request request) async {
      final body = await request.readAsString();
      final decoded = jsonDecode(body) as Map<String, dynamic>;
      if (decoded['stories'] is! List) {
        return Response(HttpStatus.badRequest, body: 'Invalid story payload');
      }
      state['stories'] = decoded['stories'];
      await _saveState(storage, state);
      return Response.ok(jsonEncode({'status': 'ok'}), headers: {'content-type': 'application/json'});
    })
    ..post('/api/chat_threads', (Request request) async {
      final body = await request.readAsString();
      final decoded = jsonDecode(body) as Map<String, dynamic>;
      if (decoded['chatThreads'] is! List) {
        return Response(HttpStatus.badRequest, body: 'Invalid chat payload');
      }
      state['chatThreads'] = decoded['chatThreads'];
      await _saveState(storage, state);
      return Response.ok(jsonEncode({'status': 'ok'}), headers: {'content-type': 'application/json'});
    });

  final logMiddleware = logRequests();
  final handler = Pipeline().addMiddleware(logMiddleware).addHandler(router);
  final server = await serve(handler, _host, _port);
  stdout.writeln('DriveCommunity sync server listening on http://${server.address.host}:${server.port}');
}

Future<Map<String, dynamic>> _loadState(File storage) async {
  if (await storage.exists()) {
    try {
      final contents = await storage.readAsString();
      return jsonDecode(contents) as Map<String, dynamic>;
    } catch (_) {
      // If state fails to load, fall back to default data.
    }
  }
  final defaultState = {
    'stories': [
      {
        'id': 'story_1',
        'title': 'Мото-мандрівка',
        'author': 'Андрій',
        'authorAvatarUrl': null,
        'location': 'Карпати',
        'description': 'Переїзд через гори, нічний табір і враження від дороги.',
        'imageUrl': 'https://picsum.photos/seed/story1/500/500',
        'videoUrl': null,
        'likes': 128,
        'views': 540,
        'createdAt': DateTime.now().subtract(const Duration(days: 1)).toIso8601String(),
        'updatedAt': DateTime.now().subtract(const Duration(days: 1)).toIso8601String(),
      },
      {
        'id': 'story_2',
        'title': 'Відео з вечірки',
        'author': 'Марія',
        'authorAvatarUrl': null,
        'location': 'Київ',
        'description': 'Нова вечірка спільноти з яскравими моментами.',
        'videoUrl': 'https://flutter.github.io/assets-for-api-docs/assets/videos/bee.mp4',
        'likes': 98,
        'views': 420,
        'createdAt': DateTime.now().subtract(const Duration(days: 2)).toIso8601String(),
        'updatedAt': DateTime.now().subtract(const Duration(days: 2)).toIso8601String(),
      },
      {
        'id': 'story_3',
        'title': 'Нова точка',
        'author': 'RiderTeam',
        'authorAvatarUrl': null,
        'location': 'Лівий берег',
        'description': 'Оновили маршрут для вечірніх поїздок.',
        'imageUrl': 'https://picsum.photos/seed/story3/500/500',
        'likes': 214,
        'views': 760,
        'createdAt': DateTime.now().subtract(const Duration(days: 3)).toIso8601String(),
        'updatedAt': DateTime.now().subtract(const Duration(days: 3)).toIso8601String(),
      },
    ],
    'chatThreads': [
      {
        'id': 'chat_igor',
        'title': 'Ігор',
        'subtitle': 'Бачиш точку збору? Заїжджаю о 19:45',
        'participants': ['Я', 'Ігор'],
        'unreadCount': 0,
        'lastUpdated': DateTime.now().subtract(const Duration(hours: 1, minutes: 10)).toIso8601String(),
        'messages': [
          {
            'id': 'msg_igor_1',
            'sender': 'Ігор',
            'text': 'Бачиш точку збору? Заїждую о 19:45',
            'type': 'text',
            'timestamp': DateTime.now().subtract(const Duration(hours: 1, minutes: 15)).toIso8601String(),
            'isMe': false,
            'status': 'read',
          },
          {
            'id': 'msg_igor_2',
            'sender': 'Я',
            'text': 'Так, бачу, буду на місці о 19:40.',
            'type': 'text',
            'timestamp': DateTime.now().subtract(const Duration(hours: 1, minutes: 10)).toIso8601String(),
            'isMe': true,
            'status': 'sent',
          },
        ],
      },
      {
        'id': 'chat_marina',
        'title': 'Марина',
        'subtitle': 'Додавайся до вечірнього маршруту',
        'participants': ['Я', 'Марина'],
        'unreadCount': 1,
        'lastUpdated': DateTime.now().subtract(const Duration(hours: 2, minutes: 10)).toIso8601String(),
        'messages': [
          {
            'id': 'msg_marina_1',
            'sender': 'Марина',
            'text': 'Додавайся до вечірнього маршруту',
            'type': 'text',
            'timestamp': DateTime.now().subtract(const Duration(hours: 2, minutes: 20)).toIso8601String(),
            'isMe': false,
            'status': 'delivered',
          },
          {
            'id': 'msg_marina_2',
            'sender': 'Я',
            'text': 'Клас, покажи маршрут і час.',
            'type': 'text',
            'timestamp': DateTime.now().subtract(const Duration(hours: 2, minutes: 10)).toIso8601String(),
            'isMe': true,
            'status': 'sent',
          },
        ],
      },
    ],
  };
  await _saveState(storage, defaultState);
  return defaultState;
}

Future<void> _saveState(File storage, Map<String, dynamic> state) async {
  await storage.writeAsString(const JsonEncoder.withIndent('  ').convert(state));
}
