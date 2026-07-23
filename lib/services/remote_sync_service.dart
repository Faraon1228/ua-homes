import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/models.dart';
import 'platform_helper.dart';

class RemoteSyncService {
  final String baseUrl;
  final http.Client _client;

  RemoteSyncService({String? baseUrl, http.Client? client})
      : baseUrl = baseUrl ?? getRemoteBaseUrl(),
        _client = client ?? http.Client();

  Uri _endpoint(String path) => Uri.parse('$baseUrl/api$path');

  Future<List<Story>> fetchStories() async {
    final response = await _client.get(_endpoint('/stories')).timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception('Failed to fetch stories: ${response.statusCode}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['stories'] as List<dynamic>)
        .map((item) => Story.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<ChatThread>> fetchChatThreads() async {
    final response = await _client.get(_endpoint('/chat_threads')).timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception('Failed to fetch chat threads: ${response.statusCode}');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['chatThreads'] as List<dynamic>)
        .map((item) => ChatThread.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<void> syncStories(List<Story> stories) async {
    final response = await _client
        .post(
          _endpoint('/stories'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'stories': stories.map((story) => story.toJson()).toList()}),
        )
        .timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception('Failed to sync stories: ${response.statusCode}');
    }
  }

  Future<void> syncChatThreads(List<ChatThread> threads) async {
    final response = await _client
        .post(
          _endpoint('/chat_threads'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'chatThreads': threads.map((thread) => thread.toJson()).toList()}),
        )
        .timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception('Failed to sync chat threads: ${response.statusCode}');
    }
  }
}
