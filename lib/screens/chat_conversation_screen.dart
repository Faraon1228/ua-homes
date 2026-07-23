import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../state/app_state.dart';

class ChatConversationScreen extends StatefulWidget {
  final ChatThread chatThread;

  const ChatConversationScreen({required this.chatThread, super.key});

  @override
  State<ChatConversationScreen> createState() => _ChatConversationScreenState();
}

class _ChatConversationScreenState extends State<ChatConversationScreen> {
  late ChatThread _thread;
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _thread = widget.chatThread;
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _sendMessage() {
    final text = _messageController.text.trim();
    if (text.isEmpty) {
      return;
    }

    final newMessage = ChatMessage(
      id: 'msg_${_thread.id}_${DateTime.now().millisecondsSinceEpoch}',
      sender: 'Я',
      text: text,
      type: ChatMessageType.text,
      timestamp: DateTime.now(),
      isMe: true,
      status: MessageStatus.sent,
    );

    setState(() {
      _thread = ChatThread(
        id: _thread.id,
        title: _thread.title,
        subtitle: text,
        participants: _thread.participants,
        unreadCount: _thread.unreadCount,
        lastUpdated: newMessage.timestamp,
        messages: [..._thread.messages, newMessage],
      );
      _messageController.clear();
    });

    context.read<AppState>().updateThread(_thread);
    _scrollToBottom();

    Future.delayed(const Duration(milliseconds: 300), () {
      if (!mounted) return;
      final autoReply = ChatMessage(
       id: 'msg_${_thread.id}_${DateTime.now().millisecondsSinceEpoch}',
       sender: _thread.title,
       text: 'Отримав, дякую! Чекаю на тебе.',
       type: ChatMessageType.text,
       timestamp: DateTime.now(),
       isMe: false,
       status: MessageStatus.delivered,
      );
      setState(() {
        _thread = ChatThread(
          id: _thread.id,
          title: _thread.title,
          subtitle: autoReply.text,
          participants: _thread.participants,
          unreadCount: _thread.unreadCount,
          lastUpdated: autoReply.timestamp,
          messages: [..._thread.messages, autoReply],
        );
      });
      context.read<AppState>().updateThread(_thread);
      _scrollToBottom();
    });
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  String _formatTime(DateTime timestamp) {
    return '${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_thread.title),
        backgroundColor: const Color(0xFF121212),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 12),
              itemCount: _thread.messages.length,
              itemBuilder: (context, index) {
                final message = _thread.messages[index];
                final isMe = message.isMe;
                return Align(
                  alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: isMe ? const Color(0xFFDE0046) : const Color(0xFF1A1A1A),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
                    child: Column(
                      crossAxisAlignment: isMe ? CrossAxisAlignment.end : CrossAxisAlignment.start,
                      children: [
                        Text(message.text, style: TextStyle(color: isMe ? Colors.white : Colors.white70)),
                        const SizedBox(height: 6),
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              _formatTime(message.timestamp),
                              style: TextStyle(color: (isMe ? Colors.white : Colors.white70).withAlpha(179), fontSize: 10),
                            ),
                            if (isMe) ...[
                              const SizedBox(width: 6),
                              Icon(
                                message.status == MessageStatus.read
                                    ? Icons.done_all
                                    : Icons.check,
                                size: 12,
                                color: Colors.white70,
                              ),
                            ],
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          Container(
            color: const Color(0xFF121212),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _messageController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      hintText: 'Напиши повідомлення...',
                      hintStyle: TextStyle(color: Colors.white54),
                      border: OutlineInputBorder(borderSide: BorderSide.none),
                      filled: true,
                      fillColor: Color(0xFF1A1A1A),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                IconButton(
                  icon: const Icon(Icons.send, color: Color(0xFFDE0046)),
                  onPressed: _sendMessage,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
