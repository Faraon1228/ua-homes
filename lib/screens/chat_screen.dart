import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import 'all_conversations_screen.dart';
import 'chat_conversation_screen.dart';

class ChatScreen extends StatelessWidget {
  const ChatScreen({super.key});

  String _formatTime(DateTime timestamp) {
    return '${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Чати'),
        backgroundColor: const Color(0xFF121212),
        actions: [
          IconButton(
            icon: const Icon(Icons.forum),
            onPressed: () {
              Navigator.push(context, MaterialPageRoute(builder: (context) => const AllConversationsScreen()));
            },
          ),
          IconButton(icon: const Icon(Icons.edit), onPressed: () {}),
        ],
      ),
      body: Consumer<AppState>(
        builder: (context, appState, child) {
          if (!appState.isLoaded) {
            return const Center(child: CircularProgressIndicator());
          }

          return ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: 12),
            itemCount: appState.chatThreads.length,
            itemBuilder: (context, index) {
              final thread = appState.chatThreads[index];
              final previewMessage = thread.messages.isNotEmpty ? thread.messages.last.text : thread.subtitle;
              final previewTime = thread.messages.isNotEmpty ? _formatTime(thread.messages.last.timestamp) : '';
              return ListTile(
                leading: const CircleAvatar(
                  backgroundColor: Color(0xFF2A2A2A),
                  child: Icon(Icons.person, color: Colors.white),
                ),
                title: Text(thread.title, style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text(previewMessage, style: const TextStyle(color: Colors.white70)),
                trailing: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(previewTime, style: const TextStyle(color: Colors.white54, fontSize: 12)),
                    if (thread.unreadCount > 0)
                      Container(
                        margin: const EdgeInsets.only(top: 4),
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFDE0046),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          '${thread.unreadCount}',
                          style: const TextStyle(color: Colors.white, fontSize: 12),
                        ),
                      ),
                  ],
                ),
                onTap: () async {
                  final updatedThread = await Navigator.push<ChatThread>(
                    context,
                    MaterialPageRoute(builder: (context) => ChatConversationScreen(chatThread: thread)),
                  );
                  if (!context.mounted) return;
                  if (updatedThread != null) {
                    await context.read<AppState>().updateThread(updatedThread);
                  }
                },
              );
            },
          );
        },
      ),
    );
  }
}
